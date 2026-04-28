"""Shared optional-import helpers for LLM providers.

Both :class:`ClaudeProvider` and :class:`OllamaProvider`
import their SDK lazily because the ``llm`` extras group
is optional. Before this helper they each duplicated the
same ``try/except ImportError`` pattern and the same
ImportError message string in ``__init__``; centralising
them removes the drift risk and keeps messaging uniform.
"""

import importlib
from types import ModuleType


def try_import(module_name: str) -> ModuleType | None:
    """Return ``importlib.import_module(module_name)`` or
    ``None`` if the module is not installed.

    :param module_name: Top-level package name (e.g.
        ``"anthropic"``).
    :return: The imported module, or ``None`` when the
        import fails with :class:`ImportError`.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:  # pragma: no cover
        return None


def require_llm_extra(
    module: ModuleType | None,
    class_name: str,
) -> None:
    """Raise a standard :class:`ImportError` when the LLM
    extras package is missing.

    Call from each provider's ``__init__`` after its
    lazy import attempt. Keeping the message in one place
    means both providers stay in sync if the install
    command or extras group name ever changes.

    :param module: The result of :func:`try_import` for
        the provider's SDK package.
    :param class_name: The provider class name used in
        the error message.
    :raises ImportError: When ``module`` is ``None``.
    """
    if module is None:
        raise ImportError(
            f"{class_name} requires the 'llm' optional "
            "dependency group. Install with: pip "
            "install unstructured-mapping[llm]"
        )
