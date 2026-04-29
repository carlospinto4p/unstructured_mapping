"""Ingestion run operations mixin for KnowledgeStore.

Provides CRUD for pipeline ingestion runs. Mixed into
:class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`.
"""

import sqlite3

from unstructured_mapping.knowledge_graph._helpers import (
    dt_to_iso,
    now_iso,
    row_to_run,
)
from unstructured_mapping.knowledge_graph.models import (
    IngestionRun,
    RunMetrics,
    RunStatus,
)


class RunMixin:
    """Ingestion run operations for :class:`KnowledgeStore`."""

    _conn: sqlite3.Connection

    def save_run(self, run: IngestionRun) -> None:
        """Insert an ingestion run record.

        :param run: The run to save.
        """
        self._conn.execute(
            "INSERT INTO ingestion_runs "
            "(run_id, started_at, finished_at, "
            "status, document_count, entity_count, "
            "relationship_count, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.run_id,
                dt_to_iso(run.started_at),
                dt_to_iso(run.finished_at),
                run.status.value,
                run.document_count,
                run.entity_count,
                run.relationship_count,
                run.error_message,
            ),
        )
        self._commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus = RunStatus.COMPLETED,
        document_count: int = 0,
        entity_count: int = 0,
        relationship_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Mark a run as finished, updating its counters.

        :param run_id: The run to finish.
        :param status: Final status (completed or failed).
        :param document_count: Documents processed.
        :param entity_count: Provenance records created
            (entity mention count, not distinct entities).
        :param relationship_count: Relationships extracted.
        :param error_message: Error details if failed.
        """
        self._conn.execute(
            "UPDATE ingestion_runs SET "
            "finished_at = ?, status = ?, "
            "document_count = ?, entity_count = ?, "
            "relationship_count = ?, "
            "error_message = ? "
            "WHERE run_id = ?",
            (
                now_iso(),
                status.value,
                document_count,
                entity_count,
                relationship_count,
                error_message,
                run_id,
            ),
        )
        self._commit()

    def save_run_metrics(self, metrics: RunMetrics) -> None:
        """Insert or replace the scorecard for a run.

        Upsert semantics so callers can persist a partial
        row mid-run (useful for long-running operations)
        and overwrite at finalisation. The row is keyed
        on :attr:`RunMetrics.run_id`, which must already
        exist in ``ingestion_runs``.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO run_metrics "
            "(run_id, chunks_processed, mentions_detected, "
            "mentions_resolved_alias, "
            "mentions_resolved_llm, llm_resolver_calls, "
            "llm_extractor_calls, proposals_saved, "
            "relationships_saved, provider_name, "
            "model_name, wall_clock_seconds, "
            "input_tokens, output_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?)",
            (
                metrics.run_id,
                metrics.chunks_processed,
                metrics.mentions_detected,
                metrics.mentions_resolved_alias,
                metrics.mentions_resolved_llm,
                metrics.llm_resolver_calls,
                metrics.llm_extractor_calls,
                metrics.proposals_saved,
                metrics.relationships_saved,
                metrics.provider_name,
                metrics.model_name,
                metrics.wall_clock_seconds,
                metrics.input_tokens,
                metrics.output_tokens,
            ),
        )
        self._commit()

    def get_run_metrics(self, run_id: str) -> RunMetrics | None:
        """Fetch the scorecard for a run, or None."""
        row = self._conn.execute(
            "SELECT run_id, chunks_processed, "
            "mentions_detected, mentions_resolved_alias, "
            "mentions_resolved_llm, llm_resolver_calls, "
            "llm_extractor_calls, proposals_saved, "
            "relationships_saved, provider_name, "
            "model_name, wall_clock_seconds, "
            "input_tokens, output_tokens "
            "FROM run_metrics WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunMetrics(
            run_id=row["run_id"],
            chunks_processed=row["chunks_processed"],
            mentions_detected=row["mentions_detected"],
            mentions_resolved_alias=(row["mentions_resolved_alias"]),
            mentions_resolved_llm=(row["mentions_resolved_llm"]),
            llm_resolver_calls=row["llm_resolver_calls"],
            llm_extractor_calls=(row["llm_extractor_calls"]),
            proposals_saved=row["proposals_saved"],
            relationships_saved=(row["relationships_saved"]),
            provider_name=row["provider_name"],
            model_name=row["model_name"],
            wall_clock_seconds=(row["wall_clock_seconds"]),
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
        )

    def find_recent_runs(self, limit: int = 20) -> list[IngestionRun]:
        """Return the most recent ingestion runs.

        :param limit: Maximum number of runs to return,
            newest first.
        :return: List of runs ordered by ``started_at``
            descending.
        """
        rows = self._conn.execute(
            "SELECT run_id, started_at, finished_at, "
            "status, document_count, entity_count, "
            "relationship_count, error_message "
            "FROM ingestion_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row_to_run(r) for r in rows]

    def get_run(self, run_id: str) -> IngestionRun | None:
        """Fetch an ingestion run by ID.

        :param run_id: The run's unique identifier.
        :return: The run, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT run_id, started_at, finished_at, "
            "status, document_count, entity_count, "
            "relationship_count, error_message "
            "FROM ingestion_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return row_to_run(row)

    def find_entities_touched_by_run(self, run_id: str) -> set[str]:
        """Return the distinct entities this run wrote
        provenance for.

        Used by the ``run_diff`` CLI to compare which
        entities each of two runs surfaced. An entity is
        "touched" when at least one provenance row tagged
        with ``run_id`` mentions it — either because the
        run created the entity (LLM proposal) or because
        the run added a new provenance row for an already-
        existing entity.

        :param run_id: Ingestion run identifier.
        :return: Set of entity IDs.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT entity_id FROM provenance WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return {r["entity_id"] for r in rows}

    #: Back-compat alias for the canonical
    #: :meth:`find_entities_touched_by_run`.
    get_entities_touched_by_run = find_entities_touched_by_run

    def save_article_failure(
        self,
        run_id: str,
        document_id: str,
        error_message: str,
    ) -> None:
        """Record a per-article failure for ``run_id``.

        Upsert semantics (``INSERT OR REPLACE``) so a
        resumed article that fails again overwrites the
        prior error rather than piling up rows. The
        ``failed_at`` timestamp is refreshed on every
        call so the most recent error is always the one
        inspectable via :meth:`find_failed_document_ids`.

        :param run_id: The run in which the article
            failed. Must exist in ``ingestion_runs`` —
            the FK on ``article_failures`` rejects
            orphans.
        :param document_id: The article that failed;
            typically the hex form of
            :attr:`Article.document_id`.
        :param error_message: Stringified exception
            from the orchestrator's per-article
            ``except`` block. Useful for post-run
            triage.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO article_failures "
            "(run_id, document_id, error_message, failed_at) "
            "VALUES (?, ?, ?, ?)",
            (run_id, document_id, error_message, now_iso()),
        )
        self._commit()

    def find_failed_document_ids(self, run_id: str) -> list[str]:
        """Return document ids that failed in ``run_id``.

        Used to drive ``--resume-run``-style re-queueing:
        the caller feeds the returned list back into the
        orchestrator to re-process only the articles that
        crashed without re-paying LLM costs for the
        successful ones.

        :param run_id: Ingestion run identifier.
        :return: Ordered list of ``document_id`` strings
            (sorted for determinism; order does not
            otherwise matter). Empty when no failures
            were recorded for the run — the caller
            should treat that as "nothing to resume".
        """
        rows = self._conn.execute(
            "SELECT document_id FROM article_failures "
            "WHERE run_id = ? ORDER BY document_id",
            (run_id,),
        ).fetchall()
        return [r["document_id"] for r in rows]

    #: Back-compat alias for the canonical
    #: :meth:`find_failed_document_ids`.
    get_failed_document_ids = find_failed_document_ids

    def find_relationship_keys_for_run(
        self, run_id: str
    ) -> set[tuple[str, str, str]]:
        """Return the relationship identity keys created by
        a run.

        The ``relationships`` primary key also includes
        ``valid_from`` so the same pair/type can coexist in
        different temporal bounds; for a cross-run diff the
        temporal component is intentionally dropped so
        "same edge, new bound" still counts as a match.

        :param run_id: Ingestion run identifier.
        :return: Set of ``(source_id, target_id,
            relation_type)`` tuples.
        """
        rows = self._conn.execute(
            "SELECT source_id, target_id, relation_type "
            "FROM relationships WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return {
            (r["source_id"], r["target_id"], r["relation_type"]) for r in rows
        }

    #: Back-compat alias for the canonical
    #: :meth:`find_relationship_keys_for_run`.
    get_relationship_keys_for_run = find_relationship_keys_for_run
