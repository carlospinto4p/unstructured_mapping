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
        self._conn.commit()

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
        :param entity_count: Entity mentions found.
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
        self._conn.commit()

    def get_run(
        self, run_id: str
    ) -> IngestionRun | None:
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
