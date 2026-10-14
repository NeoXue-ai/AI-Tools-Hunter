"""A compact count snapshot of the discovery funnel."""

from __future__ import annotations

from ai_tools_hunter.domain.metrics import FunnelMetrics
from ai_tools_hunter.storage.database import ConnectionFactory

_COUNTED_TABLES = (
    "source_events",
    "domains",
    "observations",
    "candidates",
    "candidate_versions",
    "review_decisions",
)


class MetricsStore:
    """Row counts and outcome histograms for the ops view."""

    _connection: ConnectionFactory

    def funnel_metrics(self) -> FunnelMetrics:
        """Return a compact count snapshot of the discovery funnel."""
        with self._connection() as connection:
            def count(table: str) -> int:
                return connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]

            counts = {table: count(table) for table in _COUNTED_TABLES}
            outcome_rows = connection.execute(
                "SELECT outcome_code, COUNT(*) AS count FROM observations GROUP BY outcome_code"
            ).fetchall()
        return FunnelMetrics(
            source_events=counts["source_events"],
            domains=counts["domains"],
            observations=counts["observations"],
            candidates=counts["candidates"],
            candidate_versions=counts["candidate_versions"],
            review_decisions=counts["review_decisions"],
            observation_outcomes={row["outcome_code"]: row["count"] for row in outcome_rows},
        )
