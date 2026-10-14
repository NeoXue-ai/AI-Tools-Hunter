"""Shared fixtures for the AI-Tools-Hunter test suite.

Two constraints of the sandbox this suite is sometimes run in shape this file:

* The system temp directory is not writable there — creating ``pytest-of-*``
  is denied with a ``PermissionError`` — so the session temp root is
  relocated inside the repository.
* File deletion is metered in that sandbox, so nothing here removes anything.
  Each session gets its own root instead, which keeps runs isolated without
  needing to clean up after them.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TMP_ROOT = _REPO_ROOT / ".pytest-tmp"

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe(basename: str) -> str:
    return _UNSAFE.sub("_", basename)


class _RepoTempFactory:
    """A minimal stand-in for pytest's ``TempPathFactory``.

    pytest's own factory puts its base under the system temp directory, which
    the sandbox denies; this one keeps everything inside the repository. It
    mirrors the two methods pytest's ``tmp_path`` fixture calls plus the two
    attributes its teardown reads — ``_retention_policy`` is pinned to
    ``"all"`` so nothing is ever removed.
    """

    _retention_policy = "all"

    def __init__(self, basetemp: Path) -> None:
        self._basetemp = basetemp

    def getbasetemp(self) -> Path:
        self._basetemp.mkdir(parents=True, exist_ok=True)
        return self._basetemp

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        base = self.getbasetemp()
        safe = _safe(basename)
        if not numbered:
            target = base / safe
            target.mkdir(parents=True, exist_ok=True)
            return target
        index = 0
        while True:
            target = base / f"{safe}{index}"
            try:
                target.mkdir(parents=True)
            except FileExistsError:
                index += 1
                continue
            return target


@pytest.fixture(scope="session")
def tmp_path_factory() -> _RepoTempFactory:
    """Per-session, repo-local temp root. Overrides pytest's built-in."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return _RepoTempFactory(_TMP_ROOT / f"{stamp}-{os.getpid()}")
