"""Candidate identities, their immutable versions, and strict-scan facts.

A candidate is one stable identity per root domain; every interpretation of it
(a rule pass, an LLM pass, a human edit) is appended as a new version that must
cite its own evidence. Nothing here overwrites a prior version.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ai_tools_hunter.domain.candidates import (
    Candidate,
    CandidateOutcome,
    CandidateVersion,
    CandidateVersionDraft,
    Evidence,
    EvidenceType,
    build_candidate,
)
from ai_tools_hunter.domain.verification import CandidateVerification
from ai_tools_hunter.storage.database import ConnectionFactory


def candidate_exists(connection: sqlite3.Connection, candidate_id: str) -> bool:
    """Return whether a candidate identity row is present."""
    return (
        connection.execute(
            "SELECT 1 FROM candidates WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        is not None
    )


def _row_to_version(row: sqlite3.Row) -> CandidateVersion:
    """Rebuild one immutable version, including its cited evidence."""
    return CandidateVersion(
        candidate_id=row["candidate_id"],
        version=row["version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        draft=CandidateVersionDraft(
            author_kind=row["author_kind"],
            primary_outcome=CandidateOutcome(row["primary_outcome"]),
            classification_confidence=row["classification_confidence"],
            name_suggestion=row["name_suggestion"],
            description_suggestion=row["description_suggestion"],
            evidence=tuple(
                Evidence(
                    evidence_type=EvidenceType(item["evidence_type"]),
                    quote=item["quote"],
                    url=item["url"],
                )
                for item in json.loads(row["evidence_json"])
            ),
            model_version=row["model_version"],
            category=row["category"],
            tags=tuple(json.loads(row["tags_json"])),
            pricing_model=row["pricing_model"],
            target_audience=row["target_audience"],
        ),
    )


class CandidateStore:
    """Candidate identities, append-only versions, and verifications."""

    _connection: ConnectionFactory

    def create_candidate(self, hostname: str, *, created_at: datetime) -> Candidate:
        """Create or reload the stable candidate identity for a root domain."""
        candidate = build_candidate(hostname, created_at=created_at)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO candidates (candidate_id, domain, created_at)
                VALUES (?, ?, ?)
                """,
                (candidate.candidate_id, candidate.domain, candidate.created_at.isoformat()),
            )
            row = connection.execute(
                "SELECT candidate_id, domain, created_at FROM candidates WHERE domain = ?",
                (candidate.domain,),
            ).fetchone()
        return Candidate(
            candidate_id=row["candidate_id"],
            domain=row["domain"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        """Return one stable candidate identity, if it exists."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT candidate_id, domain, created_at FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        return Candidate(
            candidate_id=row["candidate_id"],
            domain=row["domain"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def append_candidate_version(
        self,
        candidate_id: str,
        draft: CandidateVersionDraft,
        *,
        created_at: datetime,
    ) -> CandidateVersion:
        """Append a cited candidate interpretation without overwriting prior versions."""
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        evidence_json = json.dumps(
            [
                {
                    "evidence_type": evidence.evidence_type.value,
                    "quote": evidence.quote,
                    "url": evidence.url,
                }
                for evidence in draft.evidence
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        tags_json = json.dumps(draft.tags, ensure_ascii=False)
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            if exists is None:
                raise ValueError(f"cannot version unknown candidate: {candidate_id}")
            version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                "FROM candidate_versions WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()["next_version"]
            connection.execute(
                """
                INSERT INTO candidate_versions (
                    candidate_id, version, created_at, author_kind, primary_outcome,
                    classification_confidence, name_suggestion, description_suggestion,
                    category, tags_json, pricing_model, target_audience, model_version,
                    evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    version,
                    created_at.isoformat(),
                    draft.author_kind,
                    draft.primary_outcome.value,
                    draft.classification_confidence,
                    draft.name_suggestion,
                    draft.description_suggestion,
                    draft.category,
                    tags_json,
                    draft.pricing_model,
                    draft.target_audience,
                    draft.model_version,
                    evidence_json,
                ),
            )
        return CandidateVersion(
            candidate_id=candidate_id, version=version, created_at=created_at, draft=draft
        )

    def list_candidate_versions(self, candidate_id: str) -> tuple[CandidateVersion, ...]:
        """Reload every immutable rule, model, and human version in append order."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM candidate_versions WHERE candidate_id = ? ORDER BY version",
                (candidate_id,),
            ).fetchall()
        return tuple(_row_to_version(row) for row in rows)

    def get_candidate_version(
        self, candidate_id: str, version: int
    ) -> CandidateVersion | None:
        """Return one immutable candidate version without implying it is current."""
        if version < 1:
            raise ValueError("version must be positive")
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM candidate_versions
                WHERE candidate_id = ? AND version = ?
                """,
                (candidate_id, version),
            ).fetchone()
        return None if row is None else _row_to_version(row)

    def append_candidate_verification(
        self, verification: CandidateVerification
    ) -> bool:
        """Persist strict-scan facts once for an immutable candidate version."""
        with self._connection() as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM candidate_versions
                WHERE candidate_id = ? AND version = ?
                """,
                (verification.candidate_id, verification.candidate_version),
            ).fetchone()
            if exists is None:
                raise ValueError(
                    "verification references an unknown candidate version"
                )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO candidate_verifications (
                    candidate_id, candidate_version, checked_at, ct_first_seen_at,
                    rdap_tier, rdap_age_days, rdap_registration_at, dns_has_a,
                    http_status_code, final_url, canonical_url, final_root_matches
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verification.candidate_id,
                    verification.candidate_version,
                    verification.checked_at.isoformat(),
                    (
                        verification.ct_first_seen_at.isoformat()
                        if verification.ct_first_seen_at
                        else None
                    ),
                    verification.rdap_tier,
                    verification.rdap_age_days,
                    (
                        verification.rdap_registration_at.isoformat()
                        if verification.rdap_registration_at
                        else None
                    ),
                    int(verification.dns_has_a)
                    if verification.dns_has_a is not None
                    else None,
                    verification.http_status_code,
                    verification.final_url,
                    verification.canonical_url,
                    int(verification.final_root_matches)
                    if verification.final_root_matches is not None
                    else None,
                ),
            )
        return cursor.rowcount == 1

    def get_candidate_verification(
        self, candidate_id: str, candidate_version: int
    ) -> CandidateVerification | None:
        """Reload strict-scan facts for one candidate version."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM candidate_verifications
                WHERE candidate_id = ? AND candidate_version = ?
                """,
                (candidate_id, candidate_version),
            ).fetchone()
        if row is None:
            return None
        return CandidateVerification(
            candidate_id=row["candidate_id"],
            candidate_version=row["candidate_version"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
            ct_first_seen_at=(
                datetime.fromisoformat(row["ct_first_seen_at"])
                if row["ct_first_seen_at"]
                else None
            ),
            rdap_tier=row["rdap_tier"],
            rdap_age_days=row["rdap_age_days"],
            rdap_registration_at=(
                datetime.fromisoformat(row["rdap_registration_at"])
                if row["rdap_registration_at"]
                else None
            ),
            dns_has_a=bool(row["dns_has_a"])
            if row["dns_has_a"] is not None
            else None,
            http_status_code=row["http_status_code"],
            final_url=row["final_url"],
            canonical_url=row["canonical_url"],
            final_root_matches=bool(row["final_root_matches"])
            if row["final_root_matches"] is not None
            else None,
        )
