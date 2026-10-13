"""Tests for the filter funnel pipeline."""

import asyncio
from datetime import UTC, datetime, timedelta

from domainhunter.filter.pipeline import FilterPipeline
from domainhunter.filter.rdap_age import MemoryCache, Registration
from tests.support.clock import ManualClock


def _reg(days_ago: int, domain: str, registrar: str = "R") -> Registration:
    return Registration(
        domain=domain,
        registration_date=datetime.now(UTC) - timedelta(days=days_ago),
        registrar=registrar,
        statuses=(),
    )


def _fake_rdap(registrations: dict[str, Registration]):
    def fetcher(domain: str) -> Registration | None:
        return registrations.get(domain)

    return fetcher


def _fake_dns(has_a: set[str]):
    def checker(domains: list[str]) -> dict[str, object]:
        from domainhunter.filter.dns_check import DnsResult

        return {
            d: DnsResult(domain=d, has_a=d in has_a, addresses=("1.2.3.4",) if d in has_a else ())
            for d in domains
        }

    return checker


def test_funnel_keeps_tier1_only() -> None:
    regs = {
        "new.com": _reg(5, "new.com"),
        "old.com": _reg(200, "old.com"),
        "slow.com": _reg(60, "slow.com"),
    }
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(regs),
        dns_checker=_fake_dns({"new.com", "slow.com", "old.com"}),
    )
    candidates = pipeline.run(["new.com", "old.com", "slow.com"])
    kept = {c.domain for c in candidates}
    assert kept == {"new.com", "slow.com"}
    assert all(c.s2.tier in ("tier1", "tier2") for c in candidates)


def test_require_dns_drops_non_resolving() -> None:
    regs = {
        "resolves.com": _reg(5, "resolves.com"),
        "parked.com": _reg(5, "parked.com"),
    }
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(regs),
        dns_checker=_fake_dns({"resolves.com"}),
        require_dns=True,
    )
    candidates = pipeline.run(["resolves.com", "parked.com"])
    assert {c.domain for c in candidates} == {"resolves.com"}


def test_require_dns_drops_a_domain_without_a_dns_result() -> None:
    """Strict DNS mode fails closed when the resolver omits a domain."""
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap({"new.com": _reg(5, "new.com")}),
        dns_checker=lambda _domains: {},
        require_dns=True,
    )

    assert pipeline.run(["new.com"]) == ()


def test_evaluate_distinguishes_retryable_readiness_from_a_terminal_old_domain() -> None:
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(
            {
                "warming-up.com": _reg(5, "warming-up.com"),
                "old.com": _reg(200, "old.com"),
            }
        ),
        dns_checker=_fake_dns({"old.com"}),
        require_dns=True,
        drop_unknown_rdap=True,
    )

    decisions = {item.domain: item for item in pipeline.evaluate(["warming-up.com", "old.com"])}

    assert decisions["warming-up.com"].candidate is None
    assert decisions["warming-up.com"].retryable is True
    assert decisions["warming-up.com"].reason == "dns_not_ready"
    assert decisions["old.com"].candidate is None
    assert decisions["old.com"].retryable is False
    assert decisions["old.com"].reason == "rdap_too_old"


def test_unknown_rdap_is_kept_tier2_by_default() -> None:
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap({}),
        dns_checker=_fake_dns(set()),
    )
    candidates = pipeline.run(["unknown-domain.com"])
    assert len(candidates) == 1
    assert candidates[0].final_tier == "tier2"
    assert candidates[0].s2.reason == "rdap_unavailable"


def test_drop_unknown_rdap_option() -> None:
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap({}),
        dns_checker=_fake_dns(set()),
        drop_unknown_rdap=True,
    )
    assert pipeline.run(["unknown-domain.com"]) == ()


def test_an_rdap_outage_reports_the_failure_count_for_backoff() -> None:
    """A network failure stays retryable forever, with a growing failure count.

    The orchestrator feeds ``rdap_attempts`` to ``network_retry_delay`` so an
    outage backs off on the 1h/6h/24h/72h schedule instead of being re-queried
    on every funnel pass — which is how the original livelock started.
    """
    clock = ManualClock()
    cache = MemoryCache(miss_ttl=timedelta(minutes=15), clock=clock)
    pipeline = FilterPipeline(
        cache=cache,
        rdap_fetcher=lambda _domain: None,  # RDAP is down for every domain
        dns_checker=_fake_dns(set()),
        require_dns=True,
        drop_unknown_rdap=True,
    )

    observed: list[int] = []
    for _ in range(3):
        decision = pipeline.evaluate(["flaky.com"])[0]
        observed.append(decision.rdap_attempts)
        assert decision.candidate is None
        assert decision.retryable is True
        assert decision.reason == "rdap_unavailable"
        # Let the TTL lapse so the next pass actually asks RDAP again.
        clock.advance(timedelta(minutes=15))

    assert observed == [1, 2, 3]


def test_a_tld_without_an_rdap_endpoint_stays_terminal() -> None:
    """``rdap_unsupported`` is a permanent fact, not an outage worth retrying."""
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=lambda _domain: None,
        dns_checker=_fake_dns(set()),
        require_dns=True,
        drop_unknown_rdap=True,
    )

    decision = pipeline.evaluate(["example.zzzz"])[0]
    assert decision.candidate is None
    assert decision.retryable is False
    assert decision.reason == "rdap_unsupported"
    assert decision.rdap_attempts == 0


def test_cache_used_for_repeat_runs() -> None:
    regs = {"cached.com": _reg(5, "cached.com")}
    cache = MemoryCache()
    fetcher = _fake_rdap(regs)
    pipeline = FilterPipeline(
        cache=cache, rdap_fetcher=fetcher, dns_checker=_fake_dns({"cached.com"})
    )
    pipeline.run(["cached.com"])
    assert cache.get("cached.com") is not None

    # Second run hits cache — fetcher would return None if called again, but
    # the cache should prevent that.
    candidates = pipeline.run(["cached.com"])
    assert len(candidates) == 1


def test_tier_classification_by_registration_age() -> None:
    regs = {
        "a.com": _reg(5, "a.com"),
        "b.com": _reg(60, "b.com"),
        "c.com": _reg(200, "c.com"),
    }
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(regs),
        dns_checker=_fake_dns({"a.com", "b.com"}),
    )
    by_domain = {d.domain: d for d in pipeline.evaluate(["a.com", "b.com", "c.com"])}

    assert by_domain["a.com"].candidate is not None
    assert by_domain["a.com"].candidate.final_tier == "tier1"
    assert by_domain["b.com"].candidate is not None
    assert by_domain["b.com"].candidate.final_tier == "tier2"
    # An over-age registration is terminal, not something to retry.
    assert by_domain["c.com"].candidate is None
    assert by_domain["c.com"].retryable is False
    assert by_domain["c.com"].reason == "rdap_too_old"


def test_candidate_payload_shape() -> None:
    regs = {"x.com": _reg(5, "x.com")}
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(regs),
        dns_checker=_fake_dns({"x.com"}),
    )
    candidates = pipeline.run(["x.com"])
    payload = candidates[0].as_payload()
    assert set(payload) >= {"domain", "final_tier", "s1", "s2", "s3"}
    assert payload["s2"]["age_days"] == 5


def test_run_with_probe_probes_survivors() -> None:
    regs = {
        "new.com": _reg(5, "new.com"),
        "old.com": _reg(200, "old.com"),
    }
    probed: list[str] = []

    async def probe(domain: str, *, observed_at: datetime) -> dict[str, object]:
        probed.append(domain)
        return {"domain": domain, "outcome": "success"}

    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(regs),
        dns_checker=_fake_dns({"new.com"}),
    )

    async def run() -> None:
        candidates = await pipeline.run_with_probe(
            ["new.com", "old.com"], probe=probe
        )
        assert len(candidates) == 1
        assert candidates[0].probe == {"domain": "new.com", "outcome": "success"}

    asyncio.run(run())
    assert probed == ["new.com"]  # old.com dropped by age gate, never probed


def test_run_with_probe_requires_callback() -> None:
    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap({}),
        dns_checker=_fake_dns(set()),
    )

    async def run() -> None:
        import pytest

        with pytest.raises(ValueError):
            await pipeline.run_with_probe(["x.com"])

    asyncio.run(run())


def test_probe_payload_included_in_candidate() -> None:
    regs = {"p.com": _reg(5, "p.com")}

    async def probe(domain: str, *, observed_at: datetime) -> dict[str, object]:
        return {"outcome": "success", "status_code": 200}

    pipeline = FilterPipeline(
        cache=MemoryCache(),
        rdap_fetcher=_fake_rdap(regs),
        dns_checker=_fake_dns({"p.com"}),
        probe=probe,
    )

    async def run() -> None:
        candidates = await pipeline.run_with_probe(["p.com"])
        payload = candidates[0].as_payload()
        assert payload["probe"] == {"outcome": "success", "status_code": 200}

    asyncio.run(run())
