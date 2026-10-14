"""The candidate inbox: what to review, one candidate's context, and decisions."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from ai_tools_hunter.api.dependencies import StoreDep, decision_audit, review_projection
from ai_tools_hunter.domain.reviews import ReasonTag, ReviewAction, build_review_decision
from ai_tools_hunter.storage.sqlite import ConcurrentDecisionError

router = APIRouter(prefix="/v1")


class ReviewDecisionRequest(BaseModel):
    request_id: str = Field(min_length=1)
    action: ReviewAction
    reason_tags: tuple[ReasonTag, ...] = ()


class RevokeRequest(BaseModel):
    request_id: str = Field(min_length=1)
    reason: str = ""


def _require_actor(actor_id: str | None) -> str:
    """Every mutating route needs an actor; the header is the whole auth model."""
    if not actor_id or not actor_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Actor-ID is required"
        )
    return actor_id


@router.get("/review-queue")
def list_review_queue(store: StoreDep) -> dict[str, object]:
    """List only candidate versions that have no active human decision."""
    items: list[dict[str, object]] = []
    for item in store.list_review_queue():
        candidate_id = item.candidate.candidate_id
        candidate_version = item.latest_version.version
        if store.active_review_action(candidate_id, candidate_version) is not None:
            continue
        items.append(
            review_projection(
                candidate=item.candidate,
                version=item.latest_version,
                priority=item.priority,
                verification=store.get_candidate_verification(
                    candidate_id, candidate_version
                ),
                review_state="pending",
                canonical_url=item.canonical_url,
                internal_links=item.internal_links,
            )
        )
    return {"items": items}


@router.get("/candidates/{candidate_id}/versions/{candidate_version}/review-context")
def candidate_review_context(
    candidate_id: str, candidate_version: int, store: StoreDep
) -> dict[str, object]:
    """Return the immutable facts and decision history for one review page."""
    candidate = store.get_candidate(candidate_id)
    version = store.get_candidate_version(candidate_id, candidate_version)
    if candidate is None or version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate version not found",
        )
    active_action = store.active_review_action(candidate_id, candidate_version)
    payload = review_projection(
        candidate=candidate,
        version=version,
        priority=store.latest_review_priority(candidate_id),
        verification=store.get_candidate_verification(candidate_id, candidate_version),
        review_state=active_action.value if active_action is not None else "pending",
    )
    payload["audit"] = {
        "decisions": decision_audit(store, candidate_id, candidate_version)
    }
    return payload


@router.get("/candidates/{candidate_id}/review-context")
def latest_candidate_review_context(
    candidate_id: str, store: StoreDep
) -> dict[str, object]:
    """Return the latest version's context for the independent detail route."""
    candidate = store.get_candidate(candidate_id)
    versions = store.list_candidate_versions(candidate_id)
    if candidate is None or not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate not found",
        )
    version = versions[-1]
    active_action = store.active_review_action(candidate_id, version.version)
    latest_observation = store.latest_observation(candidate.domain)
    payload = review_projection(
        candidate=candidate,
        version=version,
        priority=store.latest_review_priority(candidate_id),
        verification=store.get_candidate_verification(candidate_id, version.version),
        review_state=active_action.value if active_action is not None else "pending",
        canonical_url=(
            latest_observation.canonical_url if latest_observation is not None else None
        ),
        internal_links=(
            latest_observation.internal_links if latest_observation is not None else ()
        ),
    )
    payload["audit"] = {
        "decisions": decision_audit(store, candidate_id, version.version)
    }
    return payload


@router.post(
    "/candidates/{candidate_id}/versions/{candidate_version}/decisions",
    status_code=status.HTTP_201_CREATED,
)
def append_review_decision(
    candidate_id: str,
    candidate_version: int,
    payload: ReviewDecisionRequest,
    response: Response,
    store: StoreDep,
    actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
) -> dict[str, object]:
    """Record one review action, idempotent on ``request_id``."""
    actor = _require_actor(actor_id)
    if store.get_candidate_version(candidate_id, candidate_version) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="candidate version not found"
        )
    decision = build_review_decision(
        request_id=payload.request_id,
        candidate_id=candidate_id,
        candidate_version=candidate_version,
        action=payload.action,
        actor_id=actor,
        decided_at=datetime.now(UTC),
        reason_tags=payload.reason_tags,
    )
    try:
        created = store.append_review_decision(decision)
    except ConcurrentDecisionError as conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": "concurrent decision conflict",
                "active_decision_id": conflict.active_decision_id,
                "active_request_id": conflict.active_request_id,
            },
        ) from conflict
    if not created:
        response.status_code = status.HTTP_200_OK
    return {"created": created, "decision_id": decision.decision_id}


@router.post(
    "/candidates/{candidate_id}/versions/{candidate_version}/decisions/{decision_id}/revoke"
)
def revoke_review_decision(
    candidate_id: str,
    candidate_version: int,
    decision_id: str,
    payload: RevokeRequest,
    store: StoreDep,
    actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
) -> dict[str, object]:
    """Soft-revoke a decision so the version becomes reviewable again."""
    actor = _require_actor(actor_id)
    if store.get_candidate_version(candidate_id, candidate_version) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="candidate version not found",
        )
    revoked = store.revoke_review_decision(
        decision_id,
        actor_id=actor,
        revoked_at=datetime.now(UTC),
        reason=payload.reason,
    )
    return {"revoked": revoked, "decision_id": decision_id}
