"""Triggering and observing CT discovery."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ai_tools_hunter.api.dependencies import StoreDep
from ai_tools_hunter.crawler.http_probe import HTTPProbe
from ai_tools_hunter.filter.pipeline import FilterPipeline
from ai_tools_hunter.ingest.ct_log_adapter import DEFAULT_LOG, CTLogFetcher
from ai_tools_hunter.ingest.ct_orchestrator import CTIngestOrchestrator
from ai_tools_hunter.ingest.ct_poller import CTPoller
from ai_tools_hunter.pipeline import AIToolsHunterPipeline

router = APIRouter(prefix="/v1")

_LOG_TAIL_BYTES = 262_144


class DiscoveryRunRequest(BaseModel):
    max_probes: int = Field(default=20, ge=1, le=200)


@router.post("/run/discovery")
async def run_discovery(
    payload: DiscoveryRunRequest, store: StoreDep
) -> dict[str, object]:
    """Run one strict CT log discovery pass end-to-end."""
    try:
        async with CTLogFetcher(logs=(DEFAULT_LOG,)) as fetcher:
            poller = CTPoller(store=store, fetch_page=fetcher)
            async with HTTPProbe() as probe:
                pipeline = AIToolsHunterPipeline(store=store, probe=probe)
                strict_filter = FilterPipeline(
                    tier1_days=30,
                    tier2_days=90,
                    require_dns=True,
                    drop_unknown_rdap=True,
                )
                orchestrator = CTIngestOrchestrator(
                    store=store,
                    poller=poller,
                    pipeline=pipeline,
                    probe_limit=payload.max_probes,
                    filter_pipeline=strict_filter,
                    require_first_seen=True,
                )
                summary = await orchestrator.run_once()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"discovery run failed: {error}",
        ) from error
    return {
        "status": (
            "completed"
            if summary.candidates_created > 0
            else "queued"
            if summary.pending_work > 0
            else "no_candidates"
        ),
        "next_cursor": summary.next_cursor,
        "certificates_seen": summary.certificates_seen,
        "events_added": summary.events_added,
        "roots_observed": summary.roots_observed,
        "strict_rejections": summary.strict_rejections,
        "probes_run": summary.probes_run,
        "candidates_created": summary.candidates_created,
        "source_errors": list(summary.source_errors),
        "pending_work": summary.pending_work,
    }


@router.get("/discovery/log")
def discovery_log(request: Request, tail: int = 200) -> dict[str, object]:
    """Return the tail of the discover daemon's log file (sibling of the DB)."""
    tail = max(1, min(tail, 1000))
    log_path: Path = request.app.state.discovery_log_path
    if not log_path.exists():
        return {"exists": False, "lines": []}
    with log_path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - _LOG_TAIL_BYTES))
        chunk = handle.read().decode("utf-8", errors="replace")
    return {"exists": True, "lines": chunk.splitlines()[-tail:]}


@router.get("/discovery/overview")
def discovery_overview(store: StoreDep) -> dict[str, object]:
    """Return a compact view of discovered domains and their latest probe state."""
    metrics = store.funnel_metrics()
    domains = [
        {
            "domain": snapshot.domain,
            "first_seen_at": (
                snapshot.first_seen_at.isoformat()
                if snapshot.first_seen_at is not None
                else None
            ),
            "observed_at": (
                snapshot.observed_at.isoformat()
                if snapshot.observed_at is not None
                else None
            ),
            "outcome_code": snapshot.outcome_code,
            "attempt_number": snapshot.attempt_number,
            "status_code": snapshot.status_code,
            "final_url": snapshot.final_url,
            "detail": snapshot.detail,
        }
        for snapshot in store.domain_snapshots()
    ]
    return {
        "cursor": store.get_source_cursor("ct_log"),
        "domains": domains,
        "counts": {
            "source_events": metrics.source_events,
            "domains": metrics.domains,
            "observations": metrics.observations,
            "candidates": metrics.candidates,
            "candidate_versions": metrics.candidate_versions,
            "review_queue": len(store.list_review_queue()),
        },
    }
