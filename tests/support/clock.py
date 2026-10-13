"""A hand-cranked clock for testing time-dependent retry behaviour.

``MemoryCache`` and the retry schedules are all wall-clock driven, and the
whole point of the S2 miss TTL is that it *expires*. Sleeping for real would
make the suite slow and flaky, so tests inject this instead and advance time
explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

DEFAULT_START = datetime(2026, 8, 16, tzinfo=UTC)


class ManualClock:
    """A callable clock that only moves when a test says so."""

    def __init__(self, start: datetime = DEFAULT_START) -> None:
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward and return the new time."""
        self.now += delta
        return self.now
