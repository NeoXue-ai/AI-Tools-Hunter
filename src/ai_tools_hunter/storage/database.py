"""The SQLite file itself: connection handling, schema, and upgrades.

Every store mixin in this package reaches the database through
:meth:`DatabaseBase._connection`, so the commit/rollback/foreign-key policy
lives in exactly one place.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]
"""What :meth:`DatabaseBase._connection` looks like to the store mixins.

Each mixin declares ``_connection: ConnectionFactory`` so it can use the
connection without importing the class that provides it.
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_events (
    id INTEGER PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    raw_subject TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_timestamp TEXT,
    evidence_summary TEXT,
    parser_version TEXT,
    issuer TEXT
);

CREATE TABLE IF NOT EXISTS domains (
    domain TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_domains (
    event_id INTEGER NOT NULL REFERENCES source_events(id),
    domain TEXT NOT NULL REFERENCES domains(domain),
    PRIMARY KEY (event_id, domain)
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    domain TEXT NOT NULL REFERENCES domains(domain),
    outcome_code TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    status_code INTEGER,
    final_url TEXT,
    detail TEXT,
    canonical_url TEXT,
    internal_links_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS source_cursors (
    source TEXT PRIMARY KEY,
    cursor TEXT
);

CREATE TABLE IF NOT EXISTS ct_seen_domains (
    domain TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    first_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ct_discovery_work (
    domain TEXT PRIMARY KEY REFERENCES domains(domain),
    first_observed_at TEXT NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    completed_at TEXT,
    completion_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_ct_discovery_work_due
    ON ct_discovery_work (completed_at, next_attempt_at, lease_expires_at, first_observed_at);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_versions (
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    author_kind TEXT NOT NULL,
    primary_outcome TEXT NOT NULL,
    classification_confidence REAL NOT NULL,
    name_suggestion TEXT,
    description_suggestion TEXT,
    category TEXT,
    tags_json TEXT NOT NULL,
    pricing_model TEXT,
    target_audience TEXT,
    model_version TEXT,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (candidate_id, version)
);

CREATE TABLE IF NOT EXISTS candidate_verifications (
    candidate_id TEXT NOT NULL,
    candidate_version INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    ct_first_seen_at TEXT,
    rdap_tier TEXT,
    rdap_age_days INTEGER,
    rdap_registration_at TEXT,
    dns_has_a INTEGER,
    http_status_code INTEGER,
    final_url TEXT,
    canonical_url TEXT,
    final_root_matches INTEGER,
    PRIMARY KEY (candidate_id, candidate_version),
    FOREIGN KEY (candidate_id, candidate_version)
        REFERENCES candidate_versions(candidate_id, version)
);

CREATE TABLE IF NOT EXISTS review_decisions (
    decision_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    candidate_version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    reason_tags_json TEXT NOT NULL,
    revoked_at TEXT,
    revoked_by TEXT,
    revoke_reason TEXT,
    FOREIGN KEY (candidate_id, candidate_version)
        REFERENCES candidate_versions(candidate_id, version)
);

CREATE TABLE IF NOT EXISTS review_priorities (
    id INTEGER PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
    calculated_at TEXT NOT NULL,
    score REAL NOT NULL,
    product_evidence_contribution REAL NOT NULL,
    early_presence_contribution REAL NOT NULL,
    low_exposure_contribution REAL NOT NULL,
    data_completeness_contribution REAL NOT NULL,
    formula_version TEXT NOT NULL
);

"""


class DatabaseBase:
    """Owns the database file, its schema, and the upgrade path.

    There is no schema-version table: each upgrade is written as an idempotent
    ``PRAGMA table_info`` check, so applying them to an already-current file is
    a no-op and a fresh file gets the full ``_SCHEMA`` in one script.
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        parent = self._database_path.parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # WAL is a property of the database file, so this is a no-op once the
        # file is converted. Without it the single writer blocks every reader
        # and each commit rewrites the rollback journal twice.
        connection.execute("PRAGMA journal_mode = WAL")
        # The documented safe pairing with WAL: fsync at checkpoints instead of
        # once per commit. A page of CT events then costs one durable write
        # instead of thousands of journal flushes.
        connection.execute("PRAGMA synchronous = NORMAL")
        # The sweep and the digest loop write from separate connections (and
        # possibly separate processes); wait for the lock rather than failing
        # the whole page with "database is locked".
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(_SCHEMA)
            ensure_source_events_issuer_column(connection)
            upgrade_observations_table(connection)
            upgrade_review_decisions_table(connection)
            upgrade_ct_discovery_work_table(connection)
            backfill_ct_discovery_state(connection)


def ensure_source_events_issuer_column(connection: sqlite3.Connection) -> None:
    """Add ``source_events.issuer`` to databases created before it existed."""
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(source_events)").fetchall()
    }
    if "issuer" not in columns:
        connection.execute("ALTER TABLE source_events ADD COLUMN issuer TEXT")


def upgrade_observations_table(connection: sqlite3.Connection) -> None:
    """Add the canonical-URL and internal-link columns to ``observations``."""
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(observations)").fetchall()
    }
    if "canonical_url" not in existing:
        connection.execute("ALTER TABLE observations ADD COLUMN canonical_url TEXT")
    if "internal_links_json" not in existing:
        connection.execute(
            "ALTER TABLE observations ADD COLUMN internal_links_json TEXT NOT NULL DEFAULT '[]'"
        )


def upgrade_review_decisions_table(connection: sqlite3.Connection) -> None:
    """Add the soft-revoke columns to ``review_decisions``."""
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(review_decisions)").fetchall()
    }
    if "revoked_at" not in existing:
        connection.execute("ALTER TABLE review_decisions ADD COLUMN revoked_at TEXT")
    if "revoked_by" not in existing:
        connection.execute("ALTER TABLE review_decisions ADD COLUMN revoked_by TEXT")
    if "revoke_reason" not in existing:
        connection.execute("ALTER TABLE review_decisions ADD COLUMN revoke_reason TEXT")


def upgrade_ct_discovery_work_table(connection: sqlite3.Connection) -> None:
    """Add the attempt/lease columns to ``ct_discovery_work``."""
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(ct_discovery_work)").fetchall()
    }
    if "attempt_number" not in existing:
        connection.execute(
            "ALTER TABLE ct_discovery_work ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 0"
        )
    if "next_attempt_at" not in existing:
        connection.execute("ALTER TABLE ct_discovery_work ADD COLUMN next_attempt_at TEXT")
        connection.execute(
            """
            UPDATE ct_discovery_work
            SET next_attempt_at = first_observed_at
            WHERE next_attempt_at IS NULL
            """
        )
    if "last_error" not in existing:
        connection.execute("ALTER TABLE ct_discovery_work ADD COLUMN last_error TEXT")
    if "lease_token" not in existing:
        connection.execute("ALTER TABLE ct_discovery_work ADD COLUMN lease_token TEXT")
    if "lease_expires_at" not in existing:
        connection.execute("ALTER TABLE ct_discovery_work ADD COLUMN lease_expires_at TEXT")


def backfill_ct_discovery_state(connection: sqlite3.Connection) -> None:
    """Recover durable CT state for events persisted before queue support.

    The inserts are intentionally idempotent: current installations write both
    records with each event, while an upgraded installation gains work and a
    first-seen timestamp for every historical CT event exactly once.
    """
    connection.execute(
        """
        INSERT OR IGNORE INTO ct_discovery_work (
            domain, first_observed_at, next_attempt_at
        )
        SELECT event_domains.domain, MIN(source_events.observed_at),
               MIN(source_events.observed_at)
        FROM event_domains
        JOIN source_events ON source_events.id = event_domains.event_id
        WHERE source_events.source = 'ct_log'
        GROUP BY event_domains.domain
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO ct_seen_domains (
            domain, first_seen_at, first_source
        )
        SELECT event_domains.domain, MIN(source_events.observed_at), 'ct_log'
        FROM event_domains
        JOIN source_events ON source_events.id = event_domains.event_id
        WHERE source_events.source = 'ct_log'
        GROUP BY event_domains.domain
        """
    )
