"""Shared request dependencies and the candidate review projection."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ai_tools_hunter.domain.candidates import Candidate, CandidateVersion
from ai_tools_hunter.domain.review_priority import ReviewPrioritySnapshot
from ai_tools_hunter.domain.verification import CandidateVerification
from ai_tools_hunter.storage.sqlite import SQLiteStore


def get_store(request: Request) -> SQLiteStore:
    """Return the store that :func:`~ai_tools_hunter.api.create_app` built."""
    return request.app.state.store


StoreDep = Annotated[SQLiteStore, Depends(get_store)]


def newness_payload(
    verification: CandidateVerification | None,
) -> dict[str, object]:
    """Expose only the persisted CT/RDAP facts needed to assess newness."""
    if verification is None:
        return {
            "status": "unknown",
            "checked_at": None,
            "ct_first_seen_at": None,
            "rdap_tier": None,
            "rdap_age_days": None,
            "rdap_registration_at": None,
        }
    is_proven = (
        verification.ct_first_seen_at is not None
        and verification.rdap_tier in {"tier1", "tier2"}
    )
    is_failed = verification.rdap_tier == "unknown"
    return {
        "status": "passed" if is_proven else "failed" if is_failed else "unknown",
        "checked_at": verification.checked_at.isoformat(),
        "ct_first_seen_at": (
            verification.ct_first_seen_at.isoformat()
            if verification.ct_first_seen_at is not None
            else None
        ),
        "rdap_tier": verification.rdap_tier,
        "rdap_age_days": verification.rdap_age_days,
        "rdap_registration_at": (
            verification.rdap_registration_at.isoformat()
            if verification.rdap_registration_at is not None
            else None
        ),
    }


def reachability_payload(
    verification: CandidateVerification | None,
) -> dict[str, object]:
    """Expose final-route facts without treating an absent check as success."""
    if verification is None:
        return {
            "status": "unknown",
            "http_status_code": None,
            "final_url": None,
            "canonical_url": None,
            "same_root": None,
        }
    return {
        "status": (
            "passed"
            if verification.final_root_matches is True
            else "failed"
            if verification.final_root_matches is False
            else "unknown"
        ),
        "http_status_code": verification.http_status_code,
        "final_url": verification.final_url,
        "canonical_url": verification.canonical_url,
        "same_root": verification.final_root_matches,
    }


def review_projection(
    *,
    candidate: Candidate,
    version: CandidateVersion,
    priority: ReviewPrioritySnapshot | None,
    verification: CandidateVerification | None,
    review_state: str,
    canonical_url: str | None = None,
    internal_links: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build the shared inbox/detail representation from stored facts only."""
    draft = version.draft
    score = priority.priority if priority is not None else None
    final_canonical_url = (
        verification.canonical_url
        if verification is not None and verification.canonical_url is not None
        else canonical_url
    )
    return {
        "candidate_id": candidate.candidate_id,
        "domain": candidate.domain,
        "version": version.version,
        "author_kind": draft.author_kind,
        "primary_outcome": draft.primary_outcome.value,
        "classification_confidence": draft.classification_confidence,
        "name_suggestion": draft.name_suggestion,
        "description_suggestion": draft.description_suggestion,
        "evidence": [
            {
                "type": evidence.evidence_type.value,
                "quote": evidence.quote,
                "url": evidence.url,
            }
            for evidence in draft.evidence
        ],
        "canonical_url": final_canonical_url,
        "internal_links": list(internal_links),
        "priority": (
            {
                "score": score.score,
                "formula_version": score.formula_version,
                "product_evidence_contribution": score.product_evidence_contribution,
                "early_presence_contribution": score.early_presence_contribution,
                "low_exposure_contribution": score.low_exposure_contribution,
                "data_completeness_contribution": score.data_completeness_contribution,
            }
            if score is not None
            else None
        ),
        "review_state": review_state,
        "newness": newness_payload(verification),
        "reachability": reachability_payload(verification),
    }


def decision_audit(
    store: SQLiteStore, candidate_id: str, candidate_version: int
) -> list[dict[str, object]]:
    """The append-only decision history for one exact candidate version."""
    return [
        {
            "decision_id": decision.decision_id,
            "action": decision.action.value,
            "actor_id": decision.actor_id,
            "decided_at": decision.decided_at.isoformat(),
            "reason_tags": [tag.value for tag in decision.reason_tags],
            "revoked": store.is_decision_revoked(decision.decision_id),
        }
        for decision in store.list_review_decisions(candidate_id)
        if decision.candidate_version == candidate_version
    ]
