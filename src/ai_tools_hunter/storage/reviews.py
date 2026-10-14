"""Human review decisions and the priority snapshots that order them.

Decisions are append-only and replay-safe: the same ``request_id`` is a no-op,
a *different* one against an already-decided version is a conflict, and a
decision is never deleted — only soft-revoked.
"""

from __future__ import annotations

import json
from datetime import datetime

from ai_tools_hunter.domain.review_priority import ReviewPriority, ReviewPrioritySnapshot
from ai_tools_hunter.domain.reviews import ReasonTag, ReviewAction, ReviewDecision
from ai_tools_hunter.storage.candidates import candidate_exists
from ai_tools_hunter.storage.database import (
    ConnectionFactory,
    upgrade_review_decisions_table,
)


class ConcurrentDecisionError(Exception):
    """Raised when a different request_id already holds an active decision.

    Decisions are append-only; once an unrevoked decision exists for a
    ``(candidate_id, candidate_version)`` pair, a second decision with a
    different ``request_id`` is a spec §11 concurrent conflict. The original
    active decision identifiers are surfaced so the API layer can return a
    structured 409 response.
    """

    def __init__(self, active_decision_id: str, active_request_id: str) -> None:
        super().__init__(
            f"candidate version already has an active decision "
            f"(decision_id={active_decision_id}, request_id={active_request_id})"
        )
        self.active_decision_id = active_decision_id
        self.active_request_id = active_request_id


class ReviewStore:
    """Append-only review decisions plus the versioned priority snapshots."""

    _connection: ConnectionFactory

    def append_review_decision(self, decision: ReviewDecision) -> bool:
        """Append a review action once, only when its candidate version exists.

        Per spec §11, a candidate version may only carry one active decision at
        a time. If an unrevoked decision for the same ``(candidate_id,
        candidate_version)`` already exists with a *different* ``request_id``,
        raise :class:`ConcurrentDecisionError` so the API layer can return 409.
        A replay with the same ``request_id`` is idempotent and still succeeds.

        Uses ``BEGIN IMMEDIATE`` so the active-decision lookup and the insert
        happen inside the same write transaction; without it, two threads
        issuing different request_ids can both pass the SELECT-then-INSERT
        check before either commits.
        """
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version_exists = connection.execute(
                """
                SELECT 1 FROM candidate_versions
                WHERE candidate_id = ? AND version = ?
                """,
                (decision.candidate_id, decision.candidate_version),
            ).fetchone()
            if version_exists is None:
                raise ValueError("review decision references an unknown candidate version")
            active = connection.execute(
                """
                SELECT decision_id, request_id FROM review_decisions
                WHERE candidate_id = ? AND candidate_version = ?
                  AND revoked_at IS NULL
                ORDER BY rowid DESC LIMIT 1
                """,
                (decision.candidate_id, decision.candidate_version),
            ).fetchone()
            if active is not None and active["request_id"] != decision.request_id:
                raise ConcurrentDecisionError(
                    active_decision_id=active["decision_id"],
                    active_request_id=active["request_id"],
                )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO review_decisions (
                    decision_id, request_id, candidate_id, candidate_version,
                    action, actor_id, decided_at, reason_tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.request_id,
                    decision.candidate_id,
                    decision.candidate_version,
                    decision.action.value,
                    decision.actor_id,
                    decision.decided_at.isoformat(),
                    json.dumps(decision.reason_tags, ensure_ascii=False),
                ),
            )
        return cursor.rowcount == 1

    def list_review_decisions(self, candidate_id: str) -> tuple[ReviewDecision, ...]:
        """Reload the complete append-only human decision history for a candidate."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT decision_id, request_id, candidate_id, candidate_version,
                       action, actor_id, decided_at, reason_tags_json
                FROM review_decisions
                WHERE candidate_id = ?
                ORDER BY decided_at, decision_id
                """,
                (candidate_id,),
            ).fetchall()
        return tuple(
            ReviewDecision(
                decision_id=row["decision_id"],
                request_id=row["request_id"],
                candidate_id=row["candidate_id"],
                candidate_version=row["candidate_version"],
                action=ReviewAction(row["action"]),
                actor_id=row["actor_id"],
                decided_at=datetime.fromisoformat(row["decided_at"]),
                reason_tags=tuple(ReasonTag(tag) for tag in json.loads(row["reason_tags_json"])),
            )
            for row in rows
        )

    def active_review_action(
        self, candidate_id: str, candidate_version: int
    ) -> ReviewAction | None:
        """Return the latest unrevoked decision action for one exact version."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT action FROM review_decisions
                WHERE candidate_id = ? AND candidate_version = ?
                  AND revoked_at IS NULL
                ORDER BY rowid DESC LIMIT 1
                """,
                (candidate_id, candidate_version),
            ).fetchone()
        return ReviewAction(row["action"]) if row is not None else None

    def is_version_approved(self, candidate_id: str, candidate_version: int) -> bool:
        """Return whether the current unrevoked decision is approval."""
        return (
            self.active_review_action(candidate_id, candidate_version)
            is ReviewAction.APPROVE
        )

    def revoke_review_decision(
        self,
        decision_id: str,
        *,
        actor_id: str,
        revoked_at: datetime,
        reason: str,
    ) -> bool:
        """Soft-revoke one review decision; idempotent for repeat calls."""
        if revoked_at.tzinfo is None:
            raise ValueError("revoked_at must be timezone-aware")
        if not actor_id or not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not decision_id or not decision_id.strip():
            raise ValueError("decision_id must not be empty")
        with self._connection() as connection:
            upgrade_review_decisions_table(connection)
            cursor = connection.execute(
                """
                UPDATE review_decisions
                SET revoked_at = ?, revoked_by = ?, revoke_reason = ?
                WHERE decision_id = ? AND revoked_at IS NULL
                """,
                (revoked_at.isoformat(), actor_id, reason, decision_id),
            )
        return cursor.rowcount == 1

    def is_decision_revoked(self, decision_id: str) -> bool:
        """Return whether one decision has been soft-revoked."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT revoked_at FROM review_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return row is not None and row["revoked_at"] is not None

    def append_review_priority(
        self,
        candidate_id: str,
        priority: ReviewPriority,
        *,
        calculated_at: datetime,
    ) -> int:
        """Append, never overwrite, the formula breakdown used for human ordering."""
        snapshot = ReviewPrioritySnapshot(calculated_at=calculated_at, priority=priority)
        with self._connection() as connection:
            if not candidate_exists(connection, candidate_id):
                raise ValueError(f"cannot score unknown candidate: {candidate_id}")
            cursor = connection.execute(
                """
                INSERT INTO review_priorities (
                    candidate_id, calculated_at, score, product_evidence_contribution,
                    early_presence_contribution, low_exposure_contribution,
                    data_completeness_contribution, formula_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    snapshot.calculated_at.isoformat(),
                    snapshot.priority.score,
                    snapshot.priority.product_evidence_contribution,
                    snapshot.priority.early_presence_contribution,
                    snapshot.priority.low_exposure_contribution,
                    snapshot.priority.data_completeness_contribution,
                    snapshot.priority.formula_version,
                ),
            )
        return cursor.lastrowid

    def latest_review_priority(self, candidate_id: str) -> ReviewPrioritySnapshot | None:
        """Return the latest saved calculation without recomputing inputs implicitly."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT calculated_at, score, product_evidence_contribution,
                       early_presence_contribution, low_exposure_contribution,
                       data_completeness_contribution, formula_version
                FROM review_priorities
                WHERE candidate_id = ? ORDER BY id DESC LIMIT 1
                """,
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        return ReviewPrioritySnapshot(
            calculated_at=datetime.fromisoformat(row["calculated_at"]),
            priority=ReviewPriority(
                score=row["score"],
                product_evidence_contribution=row["product_evidence_contribution"],
                early_presence_contribution=row["early_presence_contribution"],
                low_exposure_contribution=row["low_exposure_contribution"],
                data_completeness_contribution=row["data_completeness_contribution"],
                formula_version=row["formula_version"],
            ),
        )
