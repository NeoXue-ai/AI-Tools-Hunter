"""The static review console shell and the bookmark-compatible redirects."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
"""The built Vite bundle, shipped inside the installed package."""

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, bool]:
    """Liveness probe."""
    return {"ok": True}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def queue_console() -> FileResponse:
    """Serve the focused candidate inbox."""
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/review/{candidate_id}", response_class=HTMLResponse, include_in_schema=False)
def review_console(candidate_id: str) -> FileResponse:
    """Single-candidate review page: hero, evidence, gauge, decision buttons."""
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/discovery", response_class=HTMLResponse, include_in_schema=False)
def discovery_console() -> RedirectResponse:
    """Preserve old bookmarks while keeping the inbox as the only entry point."""
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/ops", response_class=HTMLResponse, include_in_schema=False)
def ops_console() -> RedirectResponse:
    """Preserve old bookmarks while keeping the inbox as the only entry point."""
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
