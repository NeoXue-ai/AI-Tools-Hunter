"""Source events, the domains they introduced, and the per-source cursor.

A source event is appended at most once (its idempotency key is unique), and
the domains it mentions are linked to it. ``ct_seen_domains`` is the durable
first-seen baseline that makes "newborn" a real signal rather than a guess.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from domainhunter.domain.events import SourceEvent
from domainhunter.domain.normalization import normalize_hostname
from domainhunter.storage.database import ConnectionFactory


class SourceEventStore:
    """Append-only source events, seen-domain bookkeeping, and cursors."""

    _connection: ConnectionFactory

    def append_source_event(self, event: SourceEvent, *, hostname: str) -> bool:
        """Append a source event exactly once and link it to a root domain."""
        with self._connection() as connection:
            seen_roots = self._seen_roots(connection, (hostname,))
            return self._append_source_event(
                connection, event, hostname=hostname, seen_roots=seen_roots
            )

    def append_source_events(
        self, records: tuple[tuple[SourceEvent, str], ...]
    ) -> int:
        """Append many events in one transaction; returns how many were new.

        One connection and one commit per *page* instead of per hostname. The
        per-event path spent more time opening connections and fsyncing the
        journal than doing work, which is what capped ingestion at a few
        hundred events per second.
        """
        if not records:
            return 0
        added = 0
        with self._connection() as connection:
            # One membership query for the whole page, not one per event.
            seen_roots = self._seen_roots(
                connection, tuple(hostname for _, hostname in records)
            )
            for event, hostname in records:
                if self._append_source_event(
                    connection, event, hostname=hostname, seen_roots=seen_roots
                ):
                    added += 1
        return added

    @staticmethod
    def _seen_roots(
        connection: sqlite3.Connection, hostnames: tuple[str, ...]
    ) -> set[str]:
        """Root domains already recorded in ``ct_seen_domains``."""
        roots = {normalize_hostname(name).registrable_domain for name in hostnames}
        if not roots:
            return set()
        placeholders = ",".join("?" for _ in roots)
        rows = connection.execute(
            f"SELECT domain FROM ct_seen_domains WHERE domain IN ({placeholders})",
            tuple(roots),
        ).fetchall()
        return {row["domain"] for row in rows}

    def _append_source_event(
        self,
        connection: sqlite3.Connection,
        event: SourceEvent,
        *,
        hostname: str,
        seen_roots: set[str],
    ) -> bool:
        """Write one event's five rows on an already-open connection.

        ``ensure_source_events_issuer_column`` used to run here on every single
        event — a ``PRAGMA table_info`` round trip per hostname, for a column
        that :meth:`DatabaseBase._initialize` already guarantees at startup.
        """
        domain = normalize_hostname(hostname).registrable_domain
        if event.source == "ct_log" and domain in seen_roots:
            # Storage amplification guard. Everything downstream reads only the
            # *first* sighting of a root — ``ct_seen_domains`` is INSERT OR
            # IGNORE and the funnel keys off ``first_seen_at`` — so re-recording
            # the same root for every certificate that mentions it buys rows,
            # index pages and disk without buying information. A single busy
            # root shows up in thousands of certificates a day, and a product
            # certificate repeats its own root across every SAN.
            #
            # The *first* sighting is always written, so ``event_domains`` keeps
            # one row per root and ``backfill_ct_discovery_state`` can still
            # rebuild the work queue from it.
            return False
        event_cursor = connection.execute(
            """
            INSERT OR IGNORE INTO source_events (
                idempotency_key, source, source_event_id, raw_subject, observed_at,
                source_timestamp, evidence_summary, parser_version, issuer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.idempotency_key,
                event.source,
                event.source_event_id,
                event.raw_subject,
                event.observed_at.isoformat(),
                event.source_timestamp.isoformat() if event.source_timestamp else None,
                event.evidence_summary,
                event.parser_version,
                event.issuer,
            ),
        )
        if event_cursor.rowcount == 0:
            return False

        event_id = event_cursor.lastrowid
        connection.execute(
            "INSERT OR IGNORE INTO domains (domain, first_seen_at) VALUES (?, ?)",
            (domain, event.observed_at.isoformat()),
        )
        connection.execute(
            "INSERT INTO event_domains (event_id, domain) VALUES (?, ?)",
            (event_id, domain),
        )
        if event.source == "ct_log":
            connection.execute(
                """
                INSERT OR IGNORE INTO ct_discovery_work (
                    domain, first_observed_at, next_attempt_at
                ) VALUES (?, ?, ?)
                """,
                (domain, event.observed_at.isoformat(), event.observed_at.isoformat()),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO ct_seen_domains (
                    domain, first_seen_at, first_source
                ) VALUES (?, ?, ?)
                """,
                (domain, event.observed_at.isoformat(), event.source),
            )
            # Later events in the same page must see this root as taken.
            seen_roots.add(domain)
        return True

    def event_domains(self, idempotency_key: str) -> tuple[str, ...]:
        """Return domains linked to one persisted source event."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_domains.domain
                FROM event_domains
                JOIN source_events ON source_events.id = event_domains.event_id
                WHERE source_events.idempotency_key = ?
                ORDER BY event_domains.domain
                """,
                (idempotency_key,),
            ).fetchall()
        return tuple(row["domain"] for row in rows)

    def list_domains(self) -> tuple[str, ...]:
        """Return known registrable domains in deterministic lexical order."""
        with self._connection() as connection:
            rows = connection.execute("SELECT domain FROM domains ORDER BY domain").fetchall()
        return tuple(row["domain"] for row in rows)

    def mark_seen(
        self, domains: tuple[str, ...], *, at: datetime, source: str
    ) -> int:
        """Record that CT logs showed these domains, keeping first-seen history.

        Returns the number of domains that were *new* (first time seen).
        """
        new_count = 0
        at_iso = at.isoformat()
        with self._connection() as connection:
            for domain in domains:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO ct_seen_domains (domain, first_seen_at, first_source)
                    VALUES (?, ?, ?)
                    """,
                    (domain, at_iso, source),
                )
                if cursor.rowcount:
                    new_count += 1
        return new_count

    def get_ct_first_seen_at(self, domain: str) -> datetime | None:
        """Return the durable first CT observation time for one root domain."""
        normalized = normalize_hostname(domain).registrable_domain
        with self._connection() as connection:
            row = connection.execute(
                "SELECT first_seen_at FROM ct_seen_domains WHERE domain = ?",
                (normalized,),
            ).fetchone()
        return datetime.fromisoformat(row["first_seen_at"]) if row is not None else None

    def is_seen(self, domain: str) -> bool:
        """Return True if the domain was ever observed in a CT log."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM ct_seen_domains WHERE domain = ?", (domain,)
            ).fetchone()
        return row is not None

    def filter_new(self, domains: tuple[str, ...]) -> tuple[str, ...]:
        """Return only domains that have never been seen in a CT log before."""
        if not domains:
            return ()
        placeholders = ",".join("?" for _ in domains)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT domain FROM ct_seen_domains WHERE domain IN ({placeholders})",
                domains,
            ).fetchall()
        known = {row["domain"] for row in rows}
        return tuple(d for d in domains if d not in known)

    def seen_domain_count(self) -> int:
        """Total number of domains ever observed across CT logs."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM ct_seen_domains"
            ).fetchone()
        return int(row["n"])

    def get_source_cursor(self, source: str) -> str | None:
        """Return the last committed cursor for one independently polled source."""
        if not source.strip():
            raise ValueError("source must not be empty")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT cursor FROM source_cursors WHERE source = ?", (source,)
            ).fetchone()
        return None if row is None else row["cursor"]

    def set_source_cursor(self, source: str, cursor: str | None) -> None:
        """Atomically replace the restart cursor after a fully persisted source page."""
        if not source.strip():
            raise ValueError("source must not be empty")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO source_cursors (source, cursor) VALUES (?, ?)
                ON CONFLICT(source) DO UPDATE SET cursor = excluded.cursor
                """,
                (source, cursor),
            )
