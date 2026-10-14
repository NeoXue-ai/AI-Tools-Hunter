"""The local SQLite store: one facade over the focused storage mixins.

Callers construct :class:`SQLiteStore` and use its flat method surface. The
implementation lives in sibling modules by responsibility:

* :mod:`~ai_tools_hunter.storage.database` — the file, schema, and upgrades
* :mod:`~ai_tools_hunter.storage.source_events` — events, seen domains, cursors
* :mod:`~ai_tools_hunter.storage.ct_work` — the CT discovery work queue
* :mod:`~ai_tools_hunter.storage.observations` — probe history and due domains
* :mod:`~ai_tools_hunter.storage.candidates` — identities, versions, verifications
* :mod:`~ai_tools_hunter.storage.reviews` — decisions and priority snapshots
* :mod:`~ai_tools_hunter.storage.metrics` — funnel counts
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_tools_hunter.domain.candidates import Candidate
from ai_tools_hunter.domain.review_queue import ReviewQueueItem
from ai_tools_hunter.storage.candidates import CandidateStore
from ai_tools_hunter.storage.ct_work import CTDiscoveryWorkLease, CTWorkStore
from ai_tools_hunter.storage.database import DatabaseBase
from ai_tools_hunter.storage.metrics import MetricsStore
from ai_tools_hunter.storage.observations import ObservationStore
from ai_tools_hunter.storage.reviews import ConcurrentDecisionError, ReviewStore
from ai_tools_hunter.storage.source_events import SourceEventStore

__all__ = ["CTDiscoveryWorkLease", "ConcurrentDecisionError", "DomainSnapshot", "SQLiteStore"]


@dataclass(frozen=True, slots=True)
class DomainSnapshot:
    """One domain's first-seen time plus the outcome of its latest probe."""

    domain: str
    first_seen_at: datetime | None
    observed_at: datetime | None
    outcome_code: str | None
    attempt_number: int | None
    status_code: int | None
    final_url: str | None
    detail: str | None


class SQLiteStore(
    DatabaseBase,
    SourceEventStore,
    CTWorkStore,
    ObservationStore,
    CandidateStore,
    ReviewStore,
    MetricsStore,
):
    """Append-only local persistence for source signals and observations."""

    def domain_snapshots(self) -> tuple[DomainSnapshot, ...]:
        """Every domain with its first-seen time and latest probe outcome.

        One query instead of one per domain: the ops view asks for this on
        every poll, and the table is large.
        """
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT domains.domain,
                       domains.first_seen_at,
                       observations.observed_at,
                       observations.outcome_code,
                       observations.attempt_number,
                       observations.status_code,
                       observations.final_url,
                       observations.detail
                FROM domains
                LEFT JOIN observations ON observations.id = (
                    SELECT id
                    FROM observations AS latest
                    WHERE latest.domain = domains.domain
                    ORDER BY latest.id DESC
                    LIMIT 1
                )
                ORDER BY domains.domain
                """
            ).fetchall()
        return tuple(
            DomainSnapshot(
                domain=row["domain"],
                first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
                observed_at=(
                    datetime.fromisoformat(row["observed_at"])
                    if row["observed_at"] is not None
                    else None
                ),
                outcome_code=row["outcome_code"],
                attempt_number=row["attempt_number"],
                status_code=row["status_code"],
                final_url=row["final_url"],
                detail=row["detail"],
            )
            for row in rows
        )

    def list_review_queue(self) -> tuple[ReviewQueueItem, ...]:
        """Project reviewable candidates by their latest saved version and score only.

        This is the one read that spans several stores, so it lives on the
        facade rather than in any single mixin.
        """
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT candidates.candidate_id, candidates.domain, candidates.created_at
                FROM candidates
                JOIN candidate_versions ON candidate_versions.candidate_id = candidates.candidate_id
                JOIN review_priorities ON review_priorities.candidate_id = candidates.candidate_id
                WHERE candidate_versions.version = (
                    SELECT MAX(latest_versions.version) FROM candidate_versions AS latest_versions
                    WHERE latest_versions.candidate_id = candidates.candidate_id
                )
                AND review_priorities.id = (
                    SELECT MAX(latest_priorities.id) FROM review_priorities AS latest_priorities
                    WHERE latest_priorities.candidate_id = candidates.candidate_id
                )
                ORDER BY review_priorities.score DESC, candidates.candidate_id ASC
                """
            ).fetchall()
        items: list[ReviewQueueItem] = []
        for row in rows:
            candidate = Candidate(
                candidate_id=row["candidate_id"],
                domain=row["domain"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            versions = self.list_candidate_versions(candidate.candidate_id)
            priority = self.latest_review_priority(candidate.candidate_id)
            if not versions or priority is None:
                continue
            latest_observation = self.latest_observation(candidate.domain)
            items.append(
                ReviewQueueItem(
                    candidate=candidate,
                    latest_version=versions[-1],
                    priority=priority,
                    canonical_url=latest_observation.canonical_url if latest_observation else None,
                    internal_links=latest_observation.internal_links if latest_observation else (),
                )
            )
        return tuple(items)
