"""Append-only observations of what a domain actually served.

An observation is never updated: each probe appends one row, and the retry
schedule is derived from the *latest* row rather than stored, so the history
stays auditable.
"""

from __future__ import annotations

import json
from datetime import datetime

from ai_tools_hunter.domain.normalization import normalize_hostname
from ai_tools_hunter.domain.observations import Observation, OutcomeCode
from ai_tools_hunter.domain.retry_policy import decide_next_action
from ai_tools_hunter.storage.database import ConnectionFactory


class ObservationStore:
    """Append and reload probe observations for known root domains."""

    _connection: ConnectionFactory

    def append_observation(self, observation: Observation) -> int:
        """Append an observation for a known root domain without replacing history."""
        domain = normalize_hostname(observation.domain).registrable_domain
        with self._connection() as connection:
            known_domain = connection.execute(
                "SELECT 1 FROM domains WHERE domain = ?", (domain,)
            ).fetchone()
            if known_domain is None:
                raise ValueError(f"cannot observe unknown domain: {domain}")
            cursor = connection.execute(
                """
                INSERT INTO observations (
                    domain, outcome_code, observed_at, attempt_number,
                    status_code, final_url, detail, canonical_url, internal_links_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    observation.outcome_code.value,
                    observation.observed_at.isoformat(),
                    observation.attempt_number,
                    observation.status_code,
                    observation.final_url,
                    observation.detail,
                    observation.canonical_url,
                    json.dumps(tuple(observation.internal_links), ensure_ascii=False),
                ),
            )
        return cursor.lastrowid

    def list_observations(self, hostname: str) -> tuple[Observation, ...]:
        """Reload immutable observations for a hostname's registrable domain."""
        domain = normalize_hostname(hostname).registrable_domain
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT domain, outcome_code, observed_at, attempt_number,
                       status_code, final_url, detail, canonical_url,
                       internal_links_json
                FROM observations
                WHERE domain = ?
                ORDER BY id
                """,
                (domain,),
            ).fetchall()
        return tuple(
            Observation(
                domain=row["domain"],
                outcome_code=OutcomeCode(row["outcome_code"]),
                observed_at=datetime.fromisoformat(row["observed_at"]),
                attempt_number=row["attempt_number"],
                status_code=row["status_code"],
                final_url=row["final_url"],
                detail=row["detail"],
                canonical_url=row["canonical_url"],
                internal_links=tuple(json.loads(row["internal_links_json"])),
            )
            for row in rows
        )

    def latest_observation(self, domain: str) -> Observation | None:
        """Return the most recent observation for a domain, if it has any."""
        observations = self.list_observations(domain)
        return observations[-1] if observations else None

    def due_domains(self, now: datetime) -> tuple[str, ...]:
        """Return domains whose latest append-only observation permits another probe."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT domains.domain, observations.outcome_code,
                       observations.observed_at, observations.attempt_number
                FROM domains
                LEFT JOIN observations ON observations.id = (
                    SELECT id
                    FROM observations AS latest
                    WHERE latest.domain = domains.domain
                    ORDER BY latest.id DESC
                    LIMIT 1
                )
                ORDER BY domains.domain
                """
            ).fetchall()

        due: list[str] = []
        for row in rows:
            if row["outcome_code"] is None:
                due.append(row["domain"])
                continue
            decision = decide_next_action(
                OutcomeCode(row["outcome_code"]),
                attempt_number=row["attempt_number"],
                now=datetime.fromisoformat(row["observed_at"]),
            )
            if decision.next_check_at is not None and decision.next_check_at <= now:
                due.append(row["domain"])
        return tuple(due)
