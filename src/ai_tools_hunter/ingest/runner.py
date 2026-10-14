"""Continuous CT discovery runner for ``ai_tools_hunter start``.

One command, started once, runs at capacity until Ctrl-C:

1. **Sweep**: pull every page from the stored cursor to the tree head
   with bounded parallelism (servers truncate pages, so the stride is
   discovered from real responses and shortfalls are repaired in place).
   Idempotent events, first-seen baseline and one work item per new root.
2. **Digest**: run funnel rounds (RDAP age, DNS, HTTP probe, optional
   LLM) until the work queue drains, then pause ``--idle-seconds`` and
   sweep again.  A fresh database starts at the tree head; ``--entries``
   or ``--hours`` can seed a one-time historical window on first run.
3. **Resume**: the cursor is checkpointed every ~50 pages, so a killed
   run continues where it stopped instead of rescanning.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ai_tools_hunter.ingest.ct_log_adapter import (
    CTLogFetchError,
    CTLogFetcher,
    CTLogTarget,
    leaf_cert_envelope,
    parse_leaf_input,
)
from ai_tools_hunter.ingest.ct_poller import CTCertificate, CTPoller
from ai_tools_hunter.storage.sqlite import SQLiteStore

_LOGGER = logging.getLogger("ai_tools_hunter.start")


@dataclass(frozen=True, slots=True)
class StartConfig:
    """Knobs for one backfill run. All bounded on purpose."""

    hours: float | None = None
    entries: int | None = None
    follow: bool = True
    idle_seconds: float = 15.0
    page_delay_seconds: float = 0.25
    claim_limit: int = 400
    round_delay_seconds: float = 10.0
    rdap_concurrency: int = 6
    dns_concurrency: int = 30
    probe_concurrency: int = 16
    page_fetch_concurrency: int = 8
    max_rounds: int | None = None
    page_max_attempts: int = 5
    # Bounded on purpose: an unbounded hand-off queue lets a fast producer
    # outrun the SQLite writer and grow memory without limit. 8 workers x 64
    # slots is ample headroom while still applying real backpressure.
    queue_maxsize: int | None = 64

    def __post_init__(self) -> None:
        if self.hours is not None and self.hours <= 0:
            raise ValueError("hours must be positive")
        if self.entries is not None and self.entries <= 0:
            raise ValueError("entries must be positive")
        if self.hours is not None and self.entries is not None:
            raise ValueError("choose at most one of hours/entries")
        if self.page_delay_seconds < 0:
            raise ValueError("page_delay_seconds must be non-negative")
        if self.claim_limit < 1:
            raise ValueError("claim_limit must be positive")
        if self.round_delay_seconds < 0:
            raise ValueError("round_delay_seconds must be non-negative")
        if self.page_fetch_concurrency < 1:
            raise ValueError("page_fetch_concurrency must be positive")
        if self.page_max_attempts < 1:
            raise ValueError("page_max_attempts must be positive")
        if self.queue_maxsize is not None and self.queue_maxsize < 1:
            raise ValueError("queue_maxsize must be positive or None")
        if self.follow and self.idle_seconds < 0:
            raise ValueError("idle_seconds must be non-negative")
        if min(
            self.rdap_concurrency, self.dns_concurrency, self.probe_concurrency
        ) < 1:
            raise ValueError("concurrency knobs must be positive")


@dataclass(frozen=True, slots=True)
class StartSummary:
    """Counts observable at the end of one backfill run."""

    ingested_entries: int
    queued_domains: int
    probes_run: int
    candidates_created: int
    rounds: int
    pending_work: int
    start_indices: dict[str, int]

    def as_payload(self) -> dict[str, object]:
        return {
            "ingested_entries": self.ingested_entries,
            "queued_domains": self.queued_domains,
            "probes_run": self.probes_run,
            "candidates_created": self.candidates_created,
            "rounds": self.rounds,
            "pending_work": self.pending_work,
            "start_indices": dict(self.start_indices),
        }


async def locate_start_index(
    fetcher: CTLogFetcher,
    *,
    log_id: str,
    since: datetime,
    tree_size: int,
) -> int:
    """Binary-search the smallest entry index whose ``notBefore`` >= ``since``.

    Unparseable entries are treated as "older than since" (the search walks
    right past them), which biases the window slightly larger — safe for a
    filter that drops over-age domains anyway.
    """
    if since.tzinfo is None:
        raise ValueError("since must be timezone-aware")
    lo, hi = 0, max(tree_size - 1, 0)
    answer = tree_size
    while lo <= hi:
        mid = (lo + hi) // 2
        stamp = await fetcher.leaf_timestamp(log_id, mid)
        if stamp is None:
            # Walk right past unparseable entries; give up after 10.
            parsed_stamp: datetime | None = None
            for probe_index in range(mid + 1, min(mid + 11, tree_size)):
                parsed_stamp = await fetcher.leaf_timestamp(log_id, probe_index)
                if parsed_stamp is not None:
                    break
            if parsed_stamp is None:
                lo = mid + 10
            elif parsed_stamp < since:
                lo = probe_index + 1
            else:
                hi = mid - 1
                answer = probe_index
            continue
        if stamp < since:
            lo = mid + 1
        else:
            hi = mid - 1
            answer = mid
    return max(0, min(answer, tree_size))


async def run_start(
    *,
    store: SQLiteStore,
    fetcher: CTLogFetcher,
    poller: CTPoller,
    digest_once,
    config: StartConfig,
    progress=None,
) -> StartSummary:
    """Run the continuous discovery loop until interrupted.

    ``digest_once()`` must run one digest-only orchestrator round
    (``orchestrator.run_once(poll=False)``); ingest owns the CT cursor.
    """
    report = progress or (lambda event: _LOGGER.info("%s", event))
    return await _run_follow(
        store=store,
        fetcher=fetcher,
        poller=poller,
        digest_once=digest_once,
        config=config,
        progress=report,
    )


async def _run_follow(
    *,
    store: SQLiteStore,
    fetcher: CTLogFetcher,
    poller: CTPoller,
    digest_once,
    config: StartConfig,
    progress,
) -> StartSummary:
    """Continuous max-speed mode: sweep cursor→head, drain the queue, repeat.

    This is ``discover`` with backfill's parallel ingest: started once, it
    keeps catching up new entries and digesting candidates until Ctrl-C.
    An empty store starts at the current tree head (future-only); a stored
    cursor resumes wherever the last run stopped.
    """
    cycle = 0
    total_ingested = 0
    total_probes = 0
    total_candidates = 0
    total_rounds = 0
    first_cycle = True
    since = (
        datetime.now(UTC) - timedelta(hours=config.hours)
        if config.hours is not None
        else None
    )
    while True:
        cycle += 1
        stored = _parse_stored_cursor(store.get_source_cursor(poller.source_name))
        unreachable_errors: dict[str, str] = {}
        tree_sizes = await fetcher.tree_sizes(
            on_error=lambda log, exc: unreachable_errors.__setitem__(
                log.log_id, f"{type(exc).__name__}: {exc}"
            )
        )
        unreachable = [
            log.log_id for log in fetcher.logs if log.log_id not in tree_sizes
        ]
        if unreachable:
            progress(
                {
                    "event": "start.logs_unreachable",
                    "logs": unreachable,
                    "errors": dict(unreachable_errors),
                    "reachable": sorted(tree_sizes),
                    "hint": "skipping these logs for this cycle; the rest keep sweeping",
                }
            )
            if not tree_sizes:
                # Every configured log is down: sweeping nothing and then
                # digesting an empty queue would spin forever. Surface it.
                raise CTLogFetchError(
                    "no CT log reachable: "
                    + "; ".join(f"{k} ({v})" for k, v in unreachable_errors.items())
                )
        resume_indices: dict[str, int] = {}
        for target in fetcher.logs:
            log_id = target.log_id
            if log_id not in tree_sizes:
                continue
            cursor = stored.get(log_id)
            if cursor is not None:
                resume_indices[log_id] = cursor
            elif first_cycle and config.entries is not None:
                resume_indices[log_id] = max(0, tree_sizes[log_id] - config.entries)
            elif first_cycle and since is not None:
                located = await locate_start_index(
                    fetcher, log_id=log_id, since=since, tree_size=tree_sizes[log_id]
                )
                resume_indices[log_id] = min(located, tree_sizes[log_id])
                if located >= tree_sizes[log_id]:
                    progress({
                        "event": "start.window_empty",
                        "log": log_id,
                        "hint": "log tail lags its public STH; use --entries N for a count-based first window",
                    })
            else:
                resume_indices[log_id] = tree_sizes[log_id]
            if cursor is None:
                # Persist the baseline *now*. A log that fails before its first
                # checkpoint would otherwise have no cursor at all, and the next
                # cycle would read "no cursor" and jump straight to whatever the
                # tree head is by then — silently skipping the whole backlog.
                _merge_cursor(
                    store, poller.source_name, log_id, resume_indices[log_id]
                )
        first_cycle = False

        # Candidates must appear while the sweep is still running, not only
        # after it finishes: ingest and digest run side by side, sharing the
        # work queue as the hand-off.
        ingest_task = asyncio.create_task(
            _ingest_window(
                store=store,
                fetcher=fetcher,
                poller=poller,
                resume_indices=resume_indices,
                tree_sizes=tree_sizes,
                config=config,
                progress=progress,
            )
        )
        digest_task = asyncio.create_task(
            _digest_alongside(
                digest_once=digest_once,
                store=store,
                config=config,
                ingest_task=ingest_task,
                progress=progress,
                cycle=cycle,
            )
        )
        try:
            ingested, queued = await ingest_task
            rounds, cycle_probes, cycle_candidates = await digest_task
        except BaseException:
            # A failed sweep must not leave the digest loop spinning against a
            # work queue that will never be refilled: cancel both and collect
            # them so the original exception is what propagates.
            for pending in (ingest_task, digest_task):
                pending.cancel()
            await asyncio.gather(ingest_task, digest_task, return_exceptions=True)
            raise
        total_ingested += ingested
        total_rounds += rounds
        total_probes += cycle_probes
        total_candidates += cycle_candidates
        progress(
            {
                "event": "start.cycle",
                "cycle": cycle,
                "cycle_ingested": ingested,
                "cycle_digest_rounds": rounds,
                "cycle_candidates": cycle_candidates,
                "queued_domains": queued,
                "pending_work": store.pending_ct_discovery_work_count(),
                "total_ingested": total_ingested,
                "total_candidates": total_candidates,
            }
        )
        await asyncio.sleep(config.idle_seconds)


async def _digest_alongside(
    *,
    digest_once,
    store: SQLiteStore,
    config: StartConfig,
    ingest_task: "asyncio.Task[object]",
    progress,
    cycle: int,
) -> tuple[int, int, int]:
    """Digest rounds running concurrently with the ingest sweep.

    Returns ``(rounds, probes, candidates)`` for the cycle. Stops when the
    sweep is finished and nothing is *due* (or the round budget for this
    cycle is exhausted).

    The exit condition is deliberately ``due``, not ``pending``. Pending
    counts every unfinished root — including ones whose retry is scheduled
    six hours out — so a single backed-off root used to keep this loop
    spinning forever, which meant the next ingest sweep never started and
    the cursor never advanced again.
    """
    rounds = 0
    probes = 0
    candidates = 0
    while True:
        due = store.due_ct_discovery_work_count(now=datetime.now(UTC))
        if ingest_task.done() and due == 0:
            return rounds, probes, candidates
        if due == 0:
            # Everything outstanding is waiting on a future retry: idle
            # instead of burning empty rounds until the sweep finishes.
            await asyncio.sleep(config.round_delay_seconds)
            continue
        summary = await digest_once()
        rounds += 1
        probes += summary.probes_run
        candidates += summary.candidates_created
        progress(
            {
                "event": "start.digest_round",
                "cycle": cycle,
                "round": rounds,
                "probes": summary.probes_run,
                "candidates": summary.candidates_created,
                "candidates_total": candidates,
                "due_work": due,
                "pending_work": store.pending_ct_discovery_work_count(),
            }
        )
        if config.max_rounds is not None and rounds >= config.max_rounds:
            return rounds, probes, candidates
        await asyncio.sleep(config.round_delay_seconds)


def _parse_stored_cursor(cursor: str | None) -> dict[str, int]:
    if not cursor:
        return {}
    try:
        raw = json.loads(cursor)
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, int)}


def _merge_cursor(
    store: SQLiteStore, source_name: str, log_id: str, index: int
) -> None:
    """Advance *one* log's entry in the shared cursor map.

    The cursor is a single JSON object keyed by ``log_id`` living in one
    ``source_cursors`` row, so writing ``json.dumps({log_id: index})``
    silently erases every other log's progress — the next cycle then
    re-reads only this log's key, treats the others as "no cursor", and
    resets them to the tree head (losing everything they had ingested).

    Read the whole map, change only our own entry, write it back. The
    write is monotonic: a cursor never moves backwards.
    """
    cursor = _parse_stored_cursor(store.get_source_cursor(source_name))
    previous = cursor.get(log_id)
    if previous is not None and previous >= index:
        return
    cursor[log_id] = index
    store.set_source_cursor(source_name, json.dumps(cursor))


@dataclass(frozen=True, slots=True)
class _WindowResult:
    """What one log's sweep actually achieved.

    ``contiguous`` is the highest index covered without a hole — *not*
    ``tree_size``. Writing ``tree_size`` unconditionally would checkpoint
    past an abandoned page and silently skip its entries forever.
    """

    ingested: int
    contiguous: int
    abandoned_spans: tuple[tuple[int, int], ...]
    probe_error: str | None = None

    @property
    def probe_failed(self) -> bool:
        """True when the very first page failed, so the stride is unknown."""
        return self.probe_error is not None


async def _ingest_window(
    *,
    store: SQLiteStore,
    fetcher: CTLogFetcher,
    poller: CTPoller,
    resume_indices: dict[str, int],
    tree_sizes: dict[str, int],
    config: StartConfig,
    progress,
) -> tuple[int, int]:
    """Ingest [resume_index, tree_size) for every log with bounded parallelism."""
    total_ingested = 0
    attempted = 0
    probe_errors: dict[str, str] = {}
    for target in fetcher.logs:
        log_id = target.log_id
        if log_id not in resume_indices or log_id not in tree_sizes:
            # Unreachable this cycle (get-sth failed): the sweep of the other
            # logs must not be held hostage by it.
            continue
        start = resume_indices[log_id]
        tree_size = tree_sizes[log_id]
        if start >= tree_size:
            continue
        attempted += 1
        result = await _ingest_log_window(
            store=store,
            fetcher=fetcher,
            poller=poller,
            log_id=log_id,
            start=start,
            tree_size=tree_size,
            config=config,
            progress=progress,
        )
        total_ingested += result.ingested
        if result.probe_failed:
            # Nothing was read, so there is nothing to checkpoint: leaving the
            # cursor alone keeps the window intact for the next cycle.
            probe_errors[log_id] = result.probe_error or "unknown error"
            continue
        # Checkpoint the *contiguous* high-water mark, never tree_size: a
        # page we gave up on leaves a hole, and claiming full coverage would
        # skip its entries on every future run.
        _merge_cursor(store, poller.source_name, log_id, result.contiguous)
        if result.abandoned_spans:
            progress(
                {
                    "event": "start.log_incomplete",
                    "log": log_id,
                    "abandoned_spans": [list(span) for span in result.abandoned_spans],
                    "covered_until": result.contiguous,
                    "tree_size": tree_size,
                    "hint": "cursor stops at the hole; these spans are retried next cycle",
                }
            )
    if attempted and len(probe_errors) == attempted:
        # Every log we tried died on its very first page. Returning quietly
        # would leave the digest loop spinning against a queue nobody will
        # ever refill, so fail loudly instead.
        raise CTLogFetchError(
            "every log's sweep failed: "
            + "; ".join(f"{log_id} ({error})" for log_id, error in probe_errors.items())
        )
    queued = store.pending_ct_discovery_work_count()
    return total_ingested, queued


async def _ingest_log_window(
    *,
    store: SQLiteStore,
    fetcher: CTLogFetcher,
    poller: CTPoller,
    log_id: str,
    start: int,
    tree_size: int,
    config: StartConfig,
    progress,
) -> _WindowResult:
    """One log's window: parallel fixed-stride page sweep, truncation-aware.

    The first probe page reveals the server's effective batch size; spans
    are swept with ``page_fetch_concurrency`` workers. Responses shorter
    than their span enqueue a repair range, so no entry is ever skipped.
    The store cursor is advanced to the highest contiguous covered index
    every ~50 pages, so an interrupted run resumes cheaply.

    Every retry is bounded. A span that fails — or answers with an empty
    entry list, which would otherwise re-request the identical range
    forever — ``page_max_attempts`` times is *abandoned* and reported, the
    queue feeding the consumer is capped at ``queue_maxsize`` so a fast
    producer cannot grow it without bound, and the returned ``contiguous``
    deliberately stops before the hole so the checkpoint never claims
    coverage it does not have.
    """
    probe_end = min(start + 499, tree_size - 1)
    try:
        probe_raw, _ = await fetcher.fetch_entries(log_id, start, probe_end)
    except Exception as error:  # noqa: BLE001 - a dead log must not sink the sweep
        _LOGGER.warning("probe page fetch failed [%s:%s]: %s", log_id, start, error)
        progress(
            {
                "event": "start.page_abandoned",
                "log": log_id,
                "span": [start, probe_end],
                "attempts": 1,
                "reason": f"{type(error).__name__}: {error}",
                "hint": "cursor stops before this span; it is retried next cycle",
            }
        )
        return _WindowResult(
            ingested=0,
            contiguous=start,
            abandoned_spans=((start, probe_end),),
            probe_error=f"{type(error).__name__}: {error}",
        )

    state = {"stride": max(len(probe_raw), 1)}
    probe_covered = start + len(probe_raw)

    spans: list[tuple[int, int]] = []
    first_span_end = min(start + 499, tree_size - 1)
    if probe_covered <= first_span_end:
        spans.append((probe_covered, first_span_end))
    cursor_pos = first_span_end + 1
    while cursor_pos < tree_size:
        spans.append((cursor_pos, min(cursor_pos + state["stride"] - 1, tree_size - 1)))
        cursor_pos += state["stride"]

    queue: asyncio.Queue[
        tuple[int, tuple[tuple[str, tuple[str, ...], str | None], int, int]] | None
    ] = asyncio.Queue(maxsize=config.queue_maxsize or 0)
    covered: dict[int, int] = {start: probe_covered}
    contiguous = start
    while contiguous in covered:
        contiguous = covered.pop(contiguous)
    certs: list[tuple[str, tuple[str, ...], str | None]] = []
    for offset, entry in enumerate(probe_raw):
        hostnames, issuer = parse_leaf_input(entry.get("leaf_input", ""))
        if not hostnames:
            continue
        certs.append((f"{log_id}:{start + offset}", hostnames, issuer))
    probe_entries = tuple(
        CTCertificate(
            source_event_id=cert_id,
            certificate=leaf_cert_envelope(hosts, issuer),
            observed_at=datetime.now(UTC),
        )
        for cert_id, hosts, issuer in certs
    )
    probe_seen, _ = await poller.ingest_entries(probe_entries)
    total_ingested = probe_seen
    pages_done = 1
    attempts: dict[tuple[int, int], int] = {}
    abandoned: list[tuple[int, int]] = []

    async def worker() -> None:
        while spans:
            span_start, span_end = spans.pop(0)
            key = (span_start, span_end)
            failure: str | None = None
            try:
                raw, _ = await fetcher.fetch_entries(log_id, span_start, span_end)
            except Exception as error:  # noqa: BLE001 - a failed page is retried below
                raw = []
                failure = f"{type(error).__name__}: {error}"
            else:
                if not raw:
                    # A 200 with zero entries is a truncation to nothing:
                    # re-requesting the identical range would spin forever.
                    failure = "empty entry list"
            if failure is not None:
                attempts[key] = attempts.get(key, 0) + 1
                if attempts[key] >= config.page_max_attempts:
                    abandoned.append(key)
                    _LOGGER.warning(
                        "abandoning page [%s:%s:%s] after %s attempts: %s",
                        log_id,
                        span_start,
                        span_end,
                        attempts[key],
                        failure,
                    )
                    progress(
                        {
                            "event": "start.page_abandoned",
                            "log": log_id,
                            "span": [span_start, span_end],
                            "attempts": attempts[key],
                            "reason": failure,
                            "hint": "cursor stops before this span; it is retried next cycle",
                        }
                    )
                    continue
                # Tail, not front: a permanently broken span must not starve
                # the rest of the window while its retries are burned.
                spans.append(key)
                await asyncio.sleep(config.page_delay_seconds)
                continue
            page_certs: list[tuple[str, tuple[str, ...], str | None]] = []
            for offset, entry in enumerate(raw):
                hostnames, issuer = parse_leaf_input(entry.get("leaf_input", ""))
                if not hostnames:
                    continue
                page_certs.append(
                    (f"{log_id}:{span_start + offset}", hostnames, issuer)
                )
            await queue.put(
                (span_start, (tuple(page_certs), span_start + len(raw), span_end))
            )
            if len(raw) < (span_end - span_start + 1):
                # Server shorted this span — repair immediately (front of the
                # queue) so the contiguous cursor pointer keeps advancing,
                # and shrink the stride to the observed response size.
                state["stride"] = min(state["stride"], max(len(raw), 1))
                spans.insert(0, (span_start + len(raw), span_end))

    async def consumer() -> None:
        nonlocal total_ingested, pages_done, contiguous
        while True:
            item = await queue.get()
            if item is None:
                return
            span_start, (page_certs, returned_end, _span_end) = item
            entries = tuple(
                CTCertificate(
                    source_event_id=cert_id,
                    certificate=leaf_cert_envelope(hosts, issuer),
                    observed_at=datetime.now(UTC),
                )
                for cert_id, hosts, issuer in page_certs
            )
            seen, _added = await poller.ingest_entries(entries)
            total_ingested += seen
            pages_done += 1
            covered[span_start] = returned_end
            while contiguous in covered:
                contiguous = covered.pop(contiguous)
            if pages_done % 50 == 0:
                _merge_cursor(store, poller.source_name, log_id, contiguous)
                progress(
                    {
                        "event": "start.ingest_progress",
                        "log": log_id,
                        "pages": pages_done,
                        "entries": total_ingested,
                        "covered_until": contiguous,
                        "window_entries": tree_size - start,
                    }
                )
            await asyncio.sleep(0)

    producers = [
        asyncio.create_task(worker())
        for _ in range(min(config.page_fetch_concurrency, max(len(spans), 1)))
    ]
    consumer_task = asyncio.create_task(consumer())

    async def close_queue_when_drained() -> None:
        await asyncio.gather(*producers)
        await queue.put(None)

    try:
        await asyncio.gather(close_queue_when_drained(), consumer_task)
    except BaseException:
        # A consumer that dies while producers are blocked on a full queue
        # would hang the gather forever: cancel both sides and re-raise.
        for task in (*producers, consumer_task):
            task.cancel()
        await asyncio.gather(*producers, consumer_task, return_exceptions=True)
        raise
    return _WindowResult(
        ingested=total_ingested,
        contiguous=contiguous,
        abandoned_spans=tuple(abandoned),
    )
