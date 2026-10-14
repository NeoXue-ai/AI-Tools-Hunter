"""The CT discovery work queue: lease, retry, and completion.

CT ingestion must probe each new root exactly once even when several sweeps
overlap, so work items are claimed under a time-bounded lease token instead of
being read and marked. This queue is the only hand-off between the ingest
sweep and the digest loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from ai_tools_hunter.storage.database import ConnectionFactory

_DUE_PREDICATE = """
    completed_at IS NULL
    AND COALESCE(next_attempt_at, first_observed_at) <= ?
    AND (lease_token IS NULL OR lease_expires_at <= ?)
"""
"""What ``claim_ct_discovery_work`` is willing to hand out.

Shared verbatim with :meth:`CTWorkStore.due_ct_discovery_work_count` so the
count and the claim can never disagree about what "due" means.
"""


@dataclass(frozen=True, slots=True)
class CTDiscoveryWorkLease:
    """One exclusive, retryable unit of CT discovery work."""

    domain: str
    attempt_number: int
    lease_token: str


class CTWorkStore:
    """Lease-based claim/retry/complete over ``ct_discovery_work``."""

    _connection: ConnectionFactory

    def list_pending_ct_discovery_domains(self, *, limit: int) -> tuple[str, ...]:
        """Return a bounded oldest-first batch of CT roots awaiting discovery."""
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT domain FROM ct_discovery_work
                WHERE completed_at IS NULL AND lease_token IS NULL
                ORDER BY next_attempt_at, first_observed_at, domain
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(row["domain"] for row in rows)

    def pending_ct_discovery_work_count(self) -> int:
        """Count unfinished CT roots, including scheduled retries and active leases."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM ct_discovery_work WHERE completed_at IS NULL"
            ).fetchone()
        return int(row["count"])

    def due_ct_discovery_work_count(self, *, now: datetime) -> int:
        """Count the CT roots that could be claimed *right now*.

        ``pending_ct_discovery_work_count`` counts every unfinished root,
        including ones whose retry is scheduled hours into the future. The
        digest loop used it as its exit condition, so a single backed-off
        root kept the loop spinning forever and the next ingest sweep never
        started. "Is there anything to do?" must mean "is anything due?".
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        stamp = now.isoformat()
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM ct_discovery_work WHERE {_DUE_PREDICATE}",
                (stamp, stamp),
            ).fetchone()
        return int(row["count"])

    def claim_ct_discovery_work(
        self, *, now: datetime, lease_seconds: float, limit: int
    ) -> tuple[CTDiscoveryWorkLease, ...]:
        """Lease due CT roots once so overlapping scans cannot duplicate probes."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if lease_seconds <= 0 or limit < 1:
            raise ValueError("lease_seconds and limit must be positive")
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""
                SELECT domain, attempt_number FROM ct_discovery_work
                WHERE {_DUE_PREDICATE}
                ORDER BY next_attempt_at, first_observed_at, domain
                LIMIT ?
                """,
                (now.isoformat(), now.isoformat(), limit),
            ).fetchall()
            leases: list[CTDiscoveryWorkLease] = []
            for row in rows:
                token = uuid4().hex
                connection.execute(
                    """
                    UPDATE ct_discovery_work
                    SET attempt_number = attempt_number + 1,
                        lease_token = ?, lease_expires_at = ?
                    WHERE domain = ?
                    """,
                    (token, lease_expires_at.isoformat(), row["domain"]),
                )
                leases.append(
                    CTDiscoveryWorkLease(
                        domain=row["domain"],
                        attempt_number=int(row["attempt_number"]) + 1,
                        lease_token=token,
                    )
                )
        return tuple(leases)

    def retry_ct_discovery_work(
        self,
        domain: str,
        *,
        lease_token: str,
        scheduled_at: datetime,
        error: str,
    ) -> bool:
        """Release a failed lease so the same root is retried at a known time."""
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if not lease_token or not error.strip():
            raise ValueError("lease_token and error must not be empty")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE ct_discovery_work
                SET next_attempt_at = ?, last_error = ?,
                    lease_token = NULL, lease_expires_at = NULL
                WHERE domain = ? AND lease_token = ? AND completed_at IS NULL
                """,
                (scheduled_at.isoformat(), error, domain, lease_token),
            )
        return cursor.rowcount == 1

    def complete_ct_discovery_domain(
        self, domain: str, *, lease_token: str, at: datetime, reason: str
    ) -> bool:
        """Mark one CT root terminal only after its discovery work is complete."""
        if at.tzinfo is None:
            raise ValueError("at must be timezone-aware")
        if not lease_token or not reason.strip():
            raise ValueError("lease_token and reason must not be empty")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE ct_discovery_work
                SET completed_at = ?, completion_reason = ?,
                    lease_token = NULL, lease_expires_at = NULL
                WHERE domain = ? AND lease_token = ? AND completed_at IS NULL
                """,
                (at.isoformat(), reason, domain, lease_token),
            )
        return cursor.rowcount == 1
