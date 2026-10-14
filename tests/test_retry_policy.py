from datetime import UTC, datetime, timedelta

import pytest

from ai_tools_hunter.domain.observations import OutcomeCode
from ai_tools_hunter.domain.retry_policy import decide_next_action, network_retry_delay


NOW = datetime(2026, 8, 16, tzinfo=UTC)


def test_dns_not_found_retries_after_six_hours() -> None:
    decision = decide_next_action(OutcomeCode.DNS_NOT_FOUND, attempt_number=1, now=NOW)
    assert decision.next_check_at == NOW + timedelta(hours=6)
    assert decision.terminal_status is None


def test_not_ready_becomes_terminal_after_seven_days() -> None:
    decision = decide_next_action(
        OutcomeCode.CONTENT_INSUFFICIENT,
        attempt_number=3,
        now=NOW,
    )
    assert decision.next_check_at == NOW + timedelta(days=7)

    terminal = decide_next_action(
        OutcomeCode.CONTENT_INSUFFICIENT,
        attempt_number=4,
        now=NOW + timedelta(days=7),
    )
    assert terminal.next_check_at is None
    assert terminal.terminal_status == "not_ready"


def test_robots_is_never_retried_automatically() -> None:
    decision = decide_next_action(OutcomeCode.ROBOTS_DISALLOWED, attempt_number=1, now=NOW)
    assert decision.next_check_at is None
    assert decision.terminal_status == "access_restricted"


def test_http_rate_limit_is_not_retried_automatically() -> None:
    decision = decide_next_action(OutcomeCode.HTTP_429, attempt_number=1, now=NOW)

    assert decision.next_check_at is None
    assert decision.terminal_status == "access_restricted"


def test_rejects_zero_attempt_even_for_terminal_outcomes() -> None:
    with pytest.raises(ValueError, match="attempt_number must be positive"):
        decide_next_action(OutcomeCode.ROBOTS_DISALLOWED, attempt_number=0, now=NOW)


def test_network_retry_delay_follows_the_shared_schedule() -> None:
    assert network_retry_delay(1) == timedelta(hours=1)
    assert network_retry_delay(2) == timedelta(hours=6)
    assert network_retry_delay(3) == timedelta(hours=24)
    assert network_retry_delay(4) == timedelta(hours=72)


def test_network_retry_delay_clamps_instead_of_terminating() -> None:
    """S2 must never give up on an unavailable RDAP endpoint.

    ``decide_next_action`` signals "give up" with ``next_check_at=None`` once a
    schedule is exhausted. That is the right answer for a dead site, but the
    wrong one here: the filter layer plan says an unavailable RDAP endpoint
    must not permanently discard a domain, so this helper can only slow down.
    """
    assert network_retry_delay(5) == timedelta(hours=72)
    assert network_retry_delay(10_000) == timedelta(hours=72)


def test_network_retry_delay_rejects_zero_attempts() -> None:
    with pytest.raises(ValueError, match="attempt_number must be positive"):
        network_retry_delay(0)
