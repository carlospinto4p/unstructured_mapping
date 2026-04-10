"""Entity detection via alias matching.

The detection stage scans text for surface forms that
match known KG entity aliases. It is "largely mechanical"
— pattern matching, not LLM inference. The resolution
stage downstream handles disambiguation.

Two components:

- :class:`EntityDetector` — abstract base class defining
  the detection interface.
- :class:`RuleBasedDetector` — concrete implementation
  using a case-insensitive trie for efficient
  multi-pattern matching against KG aliases.

Why a trie and not regex?
    A union regex (``alias1|alias2|...``) recompiles on
    every alias-set change and scales poorly beyond a few
    thousand patterns. A trie does O(n) text scan
    regardless of alias count, and supports incremental
    updates without recompilation.

See ``docs/pipeline/01_design.md`` for how detection fits
into the broader pipeline.
"""

from abc import ABC, abstractmethod
from collections import deque

from unstructured_mapping.knowledge_graph.models import (
    Entity,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
)


class EntityDetector(ABC):
    """Abstract base class for entity detection.

    Subclasses implement :meth:`detect` to find entity
    mentions in a chunk of text. The pipeline calls this
    once per chunk.
    """

    @abstractmethod
    def detect(self, chunk: Chunk) -> tuple[Mention, ...]:
        """Find entity mentions in the given chunk.

        :param chunk: The text chunk to scan.
        :return: Mentions found, ordered by
            ``span_start``.
        """


class _TrieNode:
    """Internal node for the alias trie.

    Each node stores children keyed by character, a
    failure link for Aho-Corasick traversal, and the
    set of entity IDs whose aliases end at this node.

    :param children: Mapping of character to child node.
    :param fail: Failure link for Aho-Corasick. Points
        to the longest proper suffix that is also a
        prefix of some pattern. ``None`` for the root.
    :param entity_ids: Entity IDs whose alias ends here.
    :param depth: Distance from the root (= alias
        length in characters).
    """

    __slots__ = ("children", "depth", "entity_ids", "fail")

    def __init__(self) -> None:
        self.children: dict[str, _TrieNode] = {}
        self.fail: _TrieNode | None = None
        self.entity_ids: set[str] = set()
        self.depth: int = 0


def _build_trie(
    alias_to_ids: dict[str, set[str]],
) -> _TrieNode:
    """Build an Aho-Corasick trie from alias mappings.

    Inserts all aliases (lowercased) and then computes
    failure links via BFS so the trie can match all
    patterns in a single linear scan.

    :param alias_to_ids: Mapping of lowercased alias
        to the set of entity IDs that share it.
    :return: The root node of the built trie.
    """
    root = _TrieNode()
    root.fail = root

    # -- Insert aliases --
    for alias, ids in alias_to_ids.items():
        node = root
        for ch in alias:
            if ch not in node.children:
                child = _TrieNode()
                child.depth = node.depth + 1
                node.children[ch] = child
            node = node.children[ch]
        node.entity_ids.update(ids)

    # -- Build failure links (BFS) --
    queue: deque[_TrieNode] = deque()
    for child in root.children.values():
        child.fail = root
        queue.append(child)

    while queue:
        current = queue.popleft()
        for ch, child in current.children.items():
            queue.append(child)
            fail = current.fail
            while fail is not root and ch not in fail.children:
                fail = fail.fail  # type: ignore[assignment]
            child.fail = (
                fail.children[ch]
                if ch in fail.children and fail.children[ch] is not child
                else root
            )
            # Merge output from failure chain
            child.entity_ids |= child.fail.entity_ids

    return root


def _is_word_boundary(text: str, pos: int) -> bool:
    """Check if position is a word boundary.

    A position is a word boundary if it is at the start
    or end of the text, or the adjacent character is not
    alphanumeric.

    :param text: The full text being scanned.
    :param pos: The character position to check.
    :return: ``True`` if the position is a word boundary.
    """
    if pos <= 0 or pos >= len(text):
        return True
    return not text[pos - 1].isalnum() or not text[pos].isalnum()


def _scan_trie(
    root: _TrieNode, text: str
) -> list[Mention]:
    """Scan text using the Aho-Corasick trie.

    Performs a single linear pass over the text,
    following trie transitions and failure links to find
    all alias matches. Only emits matches at word
    boundaries to avoid partial-word hits (e.g.
    ``"app"`` inside ``"application"``).

    :param root: Root of the built Aho-Corasick trie.
    :param text: The text to scan.
    :return: Mentions sorted by ``span_start``, then
        by ``span_end`` descending (longer matches
        first).
    """
    mentions: list[Mention] = []
    lower = text.lower()
    node = root

    for i, ch in enumerate(lower):
        while node is not root and ch not in node.children:
            node = node.fail  # type: ignore[assignment]
        if ch in node.children:
            node = node.children[ch]
        else:
            continue

        # Check this node and its failure chain
        check = node
        while check is not root:
            if check.entity_ids:
                start = i - check.depth + 1
                end = i + 1
                if _is_word_boundary(
                    lower, start
                ) and _is_word_boundary(lower, end):
                    mentions.append(
                        Mention(
                            surface_form=text[start:end],
                            span_start=start,
                            span_end=end,
                            candidate_ids=tuple(
                                sorted(check.entity_ids)
                            ),
                        )
                    )
            check = check.fail  # type: ignore[assignment]

    mentions.sort(
        key=lambda m: (m.span_start, -m.span_end)
    )
    return mentions


class RuleBasedDetector(EntityDetector):
    """Entity detector using Aho-Corasick alias trie.

    Builds a case-insensitive trie from KG entity
    aliases (including canonical names) and scans each
    chunk in O(n) time regardless of the number of
    aliases. Word-boundary checks prevent partial
    matches.

    :param entities: KG entities whose aliases (and
        canonical names) will be indexed for detection.

    Usage::

        entities = store.find_entities_by_status(
            EntityStatus.ACTIVE
        )
        detector = RuleBasedDetector(entities)
        mentions = detector.detect(chunk)
    """

    def __init__(self, entities: list[Entity]) -> None:
        alias_to_ids: dict[str, set[str]] = {}
        for entity in entities:
            names = (
                entity.canonical_name,
                *entity.aliases,
            )
            for name in names:
                key = name.lower()
                if key:
                    alias_to_ids.setdefault(
                        key, set()
                    ).add(entity.entity_id)
        self._root = _build_trie(alias_to_ids)
        self._alias_count = len(alias_to_ids)

    @property
    def alias_count(self) -> int:
        """Number of unique aliases indexed."""
        return self._alias_count

    def detect(self, chunk: Chunk) -> tuple[Mention, ...]:
        """Find entity mentions in the chunk text.

        :param chunk: The text chunk to scan.
        :return: Mentions ordered by ``span_start``,
            with longer matches first at the same
            position.
        """
        if not chunk.text:
            return ()
        return tuple(_scan_trie(self._root, chunk.text))
