import sqlite3
from datetime import UTC, datetime, timedelta

from domainhunter.domain.candidates import (
    CandidateOutcome,
    CandidateVersionDraft,
    Evidence,
    EvidenceType,
)
from domainhunter.domain.events import SourceEvent
from domainhunter.domain.observations import Observation, OutcomeCode
from domainhunter.domain.review_priority import (
    ReviewPriorityInputs,
    calculate_review_priority,
)
from domainhunter.domain.reviews import ReasonTag, ReviewAction, build_review_decision
from domainhunter.storage.sqlite import SQLiteStore

OBSERVED_AT = datetime(2026, 8, 16, tzinfo=UTC)


def test_appends_source_event_once_and_maps_it_to_the_registrable_domain(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    event = SourceEvent("ct_log", "argon:42", "app.example.co.uk", OBSERVED_AT)

    assert store.append_source_event(event, hostname="app.example.co.uk") is True
    assert store.append_source_event(event, hostname="app.example.co.uk") is False
    assert store.list_domains() == ("example.co.uk",)
    assert store.event_domains(event.idempotency_key) == ("example.co.uk",)


def test_ct_source_event_atomically_records_its_first_seen_time(tmp_path) -> None:
    """A persisted CT event must never outlive its first-seen audit record."""
    store = SQLiteStore(tmp_path / "domainhunter.db")
    event = SourceEvent("ct_log", "argon:42", "app.new-site.ai", OBSERVED_AT)

    assert store.append_source_event(event, hostname="app.new-site.ai") is True
    assert store.get_ct_first_seen_at("new-site.ai") == OBSERVED_AT


def test_store_rebuilds_ct_discovery_state_for_pre_queue_events(tmp_path) -> None:
    """Opening an upgraded database recovers CT events written before the work queue."""
    database = tmp_path / "domainhunter.db"
    store = SQLiteStore(database)
    event = SourceEvent("ct_log", "argon:42", "new-site.ai", OBSERVED_AT)
    assert store.append_source_event(event, hostname="new-site.ai") is True

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM ct_discovery_work")
        connection.execute("DELETE FROM ct_seen_domains")
        connection.commit()

    upgraded = SQLiteStore(database)
    work = upgraded.claim_ct_discovery_work(
        now=OBSERVED_AT, lease_seconds=60, limit=1
    )

    assert [item.domain for item in work] == ["new-site.ai"]
    assert upgraded.get_ct_first_seen_at("new-site.ai") == OBSERVED_AT


def test_ct_discovery_work_uses_a_lease_and_can_be_retried(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    event = SourceEvent("ct_log", "argon:42", "new-site.ai", OBSERVED_AT)
    store.append_source_event(event, hostname="new-site.ai")

    first = store.claim_ct_discovery_work(
        now=OBSERVED_AT, lease_seconds=60, limit=1
    )

    assert len(first) == 1
    assert first[0].domain == "new-site.ai"
    assert first[0].attempt_number == 1
    assert store.claim_ct_discovery_work(
        now=OBSERVED_AT, lease_seconds=60, limit=1
    ) == ()

    assert store.retry_ct_discovery_work(
        "new-site.ai",
        lease_token=first[0].lease_token,
        scheduled_at=OBSERVED_AT,
        error="dns_not_ready",
    ) is True

    second = store.claim_ct_discovery_work(
        now=OBSERVED_AT, lease_seconds=60, limit=1
    )
    assert len(second) == 1
    assert second[0].attempt_number == 2


def test_appends_source_event_with_issuer_and_persists_it(tmp_path) -> None:
    database = tmp_path / "domainhunter.db"
    store = SQLiteStore(database)
    event = SourceEvent(
        "ct_log",
        "argon:42",
        "example.com",
        OBSERVED_AT,
        issuer="Let's Encrypt",
    )

    assert store.append_source_event(event, hostname="example.com") is True

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT issuer FROM source_events WHERE idempotency_key = ?",
            (event.idempotency_key,),
        ).fetchone()
    assert row[0] == "Let's Encrypt"


def test_legacy_database_is_migrated_to_include_issuer_column(tmp_path) -> None:
    database = tmp_path / "domainhunter.db"
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE source_events (
                id INTEGER PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                raw_subject TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source_timestamp TEXT,
                evidence_summary TEXT,
                parser_version TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO source_events (idempotency_key, source, source_event_id, raw_subject, observed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("legacy-key", "ct_log", "legacy:1", "legacy.example.com", OBSERVED_AT.isoformat()),
        )
        connection.commit()
    finally:
        connection.close()

    store = SQLiteStore(database)

    with sqlite3.connect(database) as verify:
        columns = {row[1] for row in verify.execute("PRAGMA table_info(source_events)").fetchall()}
    assert "issuer" in columns

    event = SourceEvent(
        "ct_log",
        "argon:42",
        "example.com",
        OBSERVED_AT,
        issuer="Let's Encrypt",
    )
    assert store.append_source_event(event, hostname="example.com") is True

    with sqlite3.connect(database) as verify:
        row = verify.execute(
            "SELECT issuer FROM source_events WHERE idempotency_key = ?",
            (event.idempotency_key,),
        ).fetchone()
    assert row[0] == "Let's Encrypt"


def test_appends_observations_without_overwriting_prior_results(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    event = SourceEvent("ct_log", "argon:42", "example.com", OBSERVED_AT)
    store.append_source_event(event, hostname="example.com")
    first = Observation("example.com", OutcomeCode.CONNECT_TIMEOUT, OBSERVED_AT, 1)
    second = Observation(
        "example.com",
        OutcomeCode.SUCCESS,
        OBSERVED_AT.replace(hour=1),
        2,
        status_code=200,
        final_url="https://example.com",
    )

    store.append_observation(first)
    store.append_observation(second)

    assert store.list_observations("www.example.com") == (first, second)


def test_persists_canonical_url_and_internal_links_with_observations(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    event = SourceEvent("ct_log", "argon:42", "example.com", OBSERVED_AT)
    store.append_source_event(event, hostname="example.com")
    observation = Observation(
        "example.com",
        OutcomeCode.SUCCESS,
        OBSERVED_AT,
        1,
        status_code=200,
        final_url="https://example.com",
        canonical_url="https://example.com/",
        internal_links=(
            "https://example.com/about",
            "https://example.com/pricing",
        ),
    )

    store.append_observation(observation)
    reloaded = store.list_observations("example.com")

    assert reloaded == (observation,)


def test_upgrades_legacy_observations_table_with_canonical_columns(tmp_path) -> None:
    database = tmp_path / "domainhunter.db"
    store = SQLiteStore(database)
    event = SourceEvent("ct_log", "argon:42", "example.com", OBSERVED_AT)
    store.append_source_event(event, hostname="example.com")
    legacy = Observation(
        "example.com",
        OutcomeCode.SUCCESS,
        OBSERVED_AT,
        1,
    )
    store.append_observation(legacy)

    reopened = SQLiteStore(database)

    assert reopened.list_observations("example.com")[0].canonical_url is None
    assert reopened.list_observations("example.com")[0].internal_links == ()


def test_lists_domains_due_for_the_next_bounded_retry(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    event = SourceEvent("ct_log", "argon:42", "example.com", OBSERVED_AT)
    store.append_source_event(event, hostname="example.com")
    observation = Observation(
        "example.com",
        OutcomeCode.CONTENT_INSUFFICIENT,
        OBSERVED_AT,
        1,
    )
    store.append_observation(observation)

    assert store.due_domains(OBSERVED_AT + timedelta(hours=23)) == ()
    assert store.due_domains(OBSERVED_AT + timedelta(hours=24)) == ("example.com",)


def test_persists_source_cursor_for_restartable_polling(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")

    assert store.get_source_cursor("ct_log") is None
    store.set_source_cursor("ct_log", "argon:43")

    assert store.get_source_cursor("ct_log") == "argon:43"


def test_appends_candidate_versions_without_overwriting_model_evidence(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    candidate = store.create_candidate("app.example.com", created_at=OBSERVED_AT)
    replay = store.create_candidate("www.example.com", created_at=OBSERVED_AT.replace(hour=1))
    draft = CandidateVersionDraft(
        author_kind="llm",
        primary_outcome=CandidateOutcome.PUBLISHABLE_AI_SAAS,
        classification_confidence=0.82,
        name_suggestion="Example AI",
        description_suggestion="An AI writing assistant.",
        evidence=(
            Evidence(EvidenceType.TITLE, "Example AI", "https://example.com"),
        ),
        model_version="gpt-5.6",
    )

    assert replay.candidate_id == candidate.candidate_id
    first = store.append_candidate_version(candidate.candidate_id, draft, created_at=OBSERVED_AT)
    second = store.append_candidate_version(
        candidate.candidate_id,
        draft,
        created_at=OBSERVED_AT.replace(hour=1),
    )
    versions = store.list_candidate_versions(candidate.candidate_id)

    assert first.version == 1
    assert second.version == 2
    assert len(versions) == 2
    assert versions[0].draft.model_version == "gpt-5.6"
    assert versions[0].draft.evidence[0].quote == "Example AI"


def test_appends_review_decisions_idempotently_and_keeps_action_history(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    candidate = store.create_candidate("example.com", created_at=OBSERVED_AT)
    draft = CandidateVersionDraft(
        author_kind="rule",
        primary_outcome=CandidateOutcome.VALID_BUT_NOT_READY,
        classification_confidence=0.42,
        name_suggestion="Example",
        description_suggestion=None,
        evidence=(Evidence(EvidenceType.TITLE, "Example", "https://example.com"),),
    )
    store.append_candidate_version(candidate.candidate_id, draft, created_at=OBSERVED_AT)
    decision = build_review_decision(
        request_id="request-1",
        candidate_id=candidate.candidate_id,
        candidate_version=1,
        action=ReviewAction.DEFER,
        actor_id="reviewer-1",
        decided_at=OBSERVED_AT,
        reason_tags=(ReasonTag.INSUFFICIENT_EVIDENCE,),
    )

    assert store.append_review_decision(decision) is True
    assert store.append_review_decision(decision) is False
    decisions = store.list_review_decisions(candidate.candidate_id)

    assert len(decisions) == 1
    assert decisions[0].action is ReviewAction.DEFER
    assert decisions[0].reason_tags == (ReasonTag.INSUFFICIENT_EVIDENCE,)


def test_creates_database_in_missing_nested_directory(tmp_path) -> None:
    nested = tmp_path / "level1" / "level2" / "domainhunter.db"

    store = SQLiteStore(nested)

    assert nested.exists()
    store.list_domains()


def test_persists_review_priority_snapshots(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    candidate = store.create_candidate("example.com", created_at=OBSERVED_AT)
    priority = calculate_review_priority(
        ReviewPriorityInputs(
            product_evidence=0.8,
            early_presence=0.9,
            low_exposure=None,
            data_completeness=0.7,
        )
    )

    store.append_review_priority(candidate.candidate_id, priority, calculated_at=OBSERVED_AT)

    snapshot = store.latest_review_priority(candidate.candidate_id)
    assert snapshot is not None
    assert snapshot.priority == priority



def test_mark_seen_tracks_first_seen_history(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    at = datetime(2026, 8, 16, tzinfo=UTC)
    later = datetime(2026, 8, 17, tzinfo=UTC)

    new_count = store.mark_seen(("a.com", "b.com"), at=at, source="ct")
    assert new_count == 2
    assert store.is_seen("a.com") is True
    assert store.is_seen("b.com") is True
    assert store.is_seen("c.com") is False
    assert store.seen_domain_count() == 2

    # Re-marking keeps the first-seen timestamp.
    store.mark_seen(("a.com",), at=later, source="ct")
    assert store.seen_domain_count() == 2


def test_filter_new_returns_only_never_seen(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    at = datetime(2026, 8, 16, tzinfo=UTC)
    store.mark_seen(("old.com",), at=at, source="ct")

    fresh = store.filter_new(("old.com", "new.com", "brandnew.io"))
    assert fresh == ("new.com", "brandnew.io")


def test_filter_new_empty_and_unknown(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    assert store.filter_new(()) == ()
    assert store.filter_new(("x.com", "y.com")) == ("x.com", "y.com")
    assert store.seen_domain_count() == 0


def test_due_ct_discovery_work_count_excludes_future_retries(tmp_path) -> None:
    """``due`` must not count roots parked on a retry scheduled in the future.

    The digest loop used the *pending* count as its exit condition, so a
    single backed-off root kept it spinning forever and the next sweep never
    started. Pending stays high; due must drop to zero.
    """
    store = SQLiteStore(tmp_path / "domainhunter.db")
    store.append_source_event(
        SourceEvent("ct_log", "argon:42", "new-site.ai", OBSERVED_AT),
        hostname="new-site.ai",
    )
    lease = store.claim_ct_discovery_work(now=OBSERVED_AT, lease_seconds=60, limit=1)[0]
    later = OBSERVED_AT + timedelta(hours=6)
    assert store.retry_ct_discovery_work(
        "new-site.ai",
        lease_token=lease.lease_token,
        scheduled_at=later,
        error="dns_not_ready",
    )

    assert store.pending_ct_discovery_work_count() == 1
    assert store.due_ct_discovery_work_count(now=OBSERVED_AT) == 0
    assert store.due_ct_discovery_work_count(now=later) == 1


def test_due_ct_discovery_work_count_ignores_a_live_lease(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    store.append_source_event(
        SourceEvent("ct_log", "argon:42", "new-site.ai", OBSERVED_AT),
        hostname="new-site.ai",
    )
    store.claim_ct_discovery_work(now=OBSERVED_AT, lease_seconds=60, limit=1)

    assert store.pending_ct_discovery_work_count() == 1
    assert store.due_ct_discovery_work_count(now=OBSERVED_AT) == 0
    assert store.due_ct_discovery_work_count(
        now=OBSERVED_AT + timedelta(seconds=61)
    ) == 1


def test_due_ct_discovery_work_count_ignores_completed_roots(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    store.append_source_event(
        SourceEvent("ct_log", "argon:42", "new-site.ai", OBSERVED_AT),
        hostname="new-site.ai",
    )
    lease = store.claim_ct_discovery_work(now=OBSERVED_AT, lease_seconds=60, limit=1)[0]
    assert store.complete_ct_discovery_domain(
        "new-site.ai", lease_token=lease.lease_token, at=OBSERVED_AT, reason="rdap_too_old"
    )

    assert store.due_ct_discovery_work_count(now=OBSERVED_AT) == 0
    assert store.pending_ct_discovery_work_count() == 0


def test_append_source_events_batches_the_same_rows_as_the_single_path(tmp_path) -> None:
    """The batched path must write exactly what the per-event path wrote."""
    batched = SQLiteStore(tmp_path / "batched.db")
    single = SQLiteStore(tmp_path / "single.db")
    records = tuple(
        (
            SourceEvent("ct_log", f"argon:{i}", f"h{i}-batch.com", OBSERVED_AT),
            f"h{i}-batch.com",
        )
        for i in range(5)
    )

    assert batched.append_source_events(records) == 5
    for event, hostname in records:
        assert single.append_source_event(event, hostname=hostname) is True

    def dump(store: SQLiteStore) -> dict[str, list[tuple]]:
        with store._connection() as connection:
            return {
                table: [
                    tuple(row)
                    for row in connection.execute(f"SELECT * FROM {table}").fetchall()
                ]
                for table in (
                    "source_events",
                    "domains",
                    "event_domains",
                    "ct_seen_domains",
                    "ct_discovery_work",
                )
            }

    assert dump(batched) == dump(single)


def test_append_source_events_is_idempotent_across_batches(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "domainhunter.db")
    records = (
        (SourceEvent("ct_log", "argon:1", "a-batch.com", OBSERVED_AT), "a-batch.com"),
        (SourceEvent("ct_log", "argon:2", "b-batch.com", OBSERVED_AT), "b-batch.com"),
    )

    assert store.append_source_events(records) == 2
    assert store.append_source_events(records) == 0
    assert store.append_source_events(()) == 0


def test_connection_enables_wal_and_normal_synchronous(tmp_path) -> None:
    """journal_mode=delete + synchronous=FULL made every commit fsync twice."""
    store = SQLiteStore(tmp_path / "domainhunter.db")
    with store._connection() as connection:
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal == "wal"
    assert synchronous == 1  # NORMAL
    assert busy_timeout > 0


def test_repeat_sightings_of_a_known_root_are_not_recorded_again(tmp_path) -> None:
    """A busy root must not be rewritten for every certificate mentioning it.

    Everything downstream reads only the *first* sighting, so the repeat rows
    bought index pages and disk without buying information. A single busy root
    appears in thousands of certificates a day.
    """
    store = SQLiteStore(tmp_path / "domainhunter.db")
    first = SourceEvent("ct_log", "argon:1", "example.com", OBSERVED_AT)
    second = SourceEvent("ct_log", "argon:2", "www.example.com", OBSERVED_AT)

    assert store.append_source_event(first, hostname="example.com") is True
    assert store.append_source_event(second, hostname="www.example.com") is False

    with store._connection() as connection:
        events = connection.execute(
            "SELECT COUNT(*) AS n FROM source_events"
        ).fetchone()["n"]
        links = connection.execute(
            "SELECT COUNT(*) AS n FROM event_domains"
        ).fetchone()["n"]
    assert events == 1
    assert links == 1
    # The root is still recorded exactly once, so the work queue stays rebuildable.
    assert store.get_ct_first_seen_at("example.com") == OBSERVED_AT
    assert store.pending_ct_discovery_work_count() == 1
    assert store.list_domains() == ("example.com",)


def test_batched_page_records_one_event_per_new_root(tmp_path) -> None:
    """Dedup must hold *within* a page, not only across pages.

    Distinct ``source_event_id`` values, so the idempotency key cannot be
    what rejects the middle record — only the already-recorded root can.
    """
    store = SQLiteStore(tmp_path / "domainhunter.db")
    records = (
        (SourceEvent("ct_log", "argon:1", "a.example.com", OBSERVED_AT), "a.example.com"),
        (SourceEvent("ct_log", "argon:2", "b.example.com", OBSERVED_AT), "b.example.com"),
        (SourceEvent("ct_log", "argon:3", "other.com", OBSERVED_AT), "other.com"),
    )

    assert store.append_source_events(records) == 2
    assert store.list_domains() == ("example.com", "other.com")


def test_non_ct_sources_keep_every_event(tmp_path) -> None:
    """The amplification guard is CT-specific: other sources are not deduped."""
    store = SQLiteStore(tmp_path / "domainhunter.db")
    first = SourceEvent("manual", "m:1", "example.com", OBSERVED_AT)
    second = SourceEvent("manual", "m:2", "www.example.com", OBSERVED_AT)

    assert store.append_source_event(first, hostname="example.com") is True
    assert store.append_source_event(second, hostname="www.example.com") is True

    with store._connection() as connection:
        events = connection.execute(
            "SELECT COUNT(*) AS n FROM source_events"
        ).fetchone()["n"]
    assert events == 2
