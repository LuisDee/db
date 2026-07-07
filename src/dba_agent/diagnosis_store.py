"""Persists every diagnosis synthesis produces, for the accepted-rate
metric (docs/dba-agent-spec.md §4: "Every diagnosis is persisted with
its eventual reactions"). Stdlib `sqlite3` only, own schema, own file --
deliberately not sharing a database with the sibling dedup/cooldown
task's own SQLite persistence (tasks/triage/dedup-cooldown.md); these
are two independent pieces of state with different lifecycles (a
diagnosis is written once and updated only when a reaction eventually
arrives, cooldown state churns per-fingerprint on every alert).

There is no Slack reaction listener yet (tasks/listener/ is a separate,
not-yet-built piece), so `reactions` starts NULL and is only ever
populated by a caller invoking `update_reactions` by hand -- the schema
and the update path exist and are tested; nothing currently calls them
outside tests.

The evidence bundle is stored as JSON built from the already-redacted
`QueryResult.rows` the executor hands back (redact_columns already
applied there -- see executor.py) -- safe to store as-is, no further
redaction needed here. `json.dumps(..., default=str)` guards against any
row value type sqlite/json can't natively represent (e.g. a driver
returning a Decimal or datetime) without ever raising on write; the
worst case is a stringified value in the audit trail, not a crash.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from dba_agent.classifier import Classification
from dba_agent.executor import EvidenceBundle
from dba_agent.synthesis import Diagnosis

_SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    fingerprint TEXT NOT NULL,
    alert_class TEXT NOT NULL,
    host TEXT,
    subject TEXT,
    severity TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    verdict TEXT NOT NULL,
    detail TEXT NOT NULL,
    has_findings INTEGER NOT NULL,
    owner TEXT,
    reply_text TEXT NOT NULL,
    reactions_json TEXT
);
"""


@dataclass(frozen=True)
class StoredDiagnosis:
    id: int
    created_at: str
    fingerprint: str
    alert_class: str
    host: str | None
    subject: str | None
    severity: str
    evidence: dict
    verdict: str
    detail: str
    has_findings: bool
    owner: str | None
    reply_text: str
    reactions: dict | None


def _evidence_to_dict(evidence: EvidenceBundle) -> dict:
    return {
        "playbook_key": evidence.playbook_key,
        "endpoint_key": evidence.endpoint_key,
        "results": [
            {
                "query_name": r.query_name,
                "sql": r.sql,
                "columns": list(r.columns),
                "rows": [list(row) for row in r.rows] if r.rows is not None else None,
                "error": r.error,
                "duration_seconds": r.duration_seconds,
            }
            for r in evidence.results
        ],
    }


def _row_to_stored_diagnosis(row: sqlite3.Row) -> StoredDiagnosis:
    return StoredDiagnosis(
        id=row["id"],
        created_at=row["created_at"],
        fingerprint=row["fingerprint"],
        alert_class=row["alert_class"],
        host=row["host"],
        subject=row["subject"],
        severity=row["severity"],
        evidence=json.loads(row["evidence_json"]),
        verdict=row["verdict"],
        detail=row["detail"],
        has_findings=bool(row["has_findings"]),
        owner=row["owner"],
        reply_text=row["reply_text"],
        reactions=json.loads(row["reactions_json"]) if row["reactions_json"] is not None else None,
    )


class DiagnosisStore:
    """One instance per (opened) database file. `db_path` is always an
    explicit constructor argument -- never hardcoded to a fixed path --
    so tests point it at `tmp_path` and callers own where `var/
    diagnoses.sqlite3` actually lives.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record(
        self,
        classification: Classification,
        evidence: EvidenceBundle,
        diagnosis: Diagnosis,
        reply_text: str,
    ) -> int:
        """Insert one diagnosis row. Returns its id, so a caller can later
        call update_reactions once a real reaction arrives.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO diagnoses (
                fingerprint, alert_class, host, subject, severity,
                evidence_json, verdict, detail, has_findings, owner, reply_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                classification.fingerprint,
                classification.alert_class,
                classification.host,
                classification.subject,
                classification.severity,
                json.dumps(_evidence_to_dict(evidence), default=str),
                diagnosis.verdict,
                diagnosis.detail,
                int(diagnosis.has_findings),
                diagnosis.owner,
                reply_text,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def update_reactions(self, diagnosis_id: int, reactions: dict) -> None:
        """Update the reactions field for an already-persisted diagnosis.
        No Slack reaction listener exists yet to call this for real
        (docs/dba-agent-spec.md §4's listener captures 👍/👎 as the
        usefulness metric, but that wiring is a separate, not-yet-built
        task) -- this method and column exist so that future listener has
        somewhere to write to, proven here with a hand-set value.
        """
        self._conn.execute(
            "UPDATE diagnoses SET reactions_json = ? WHERE id = ?",
            (json.dumps(reactions, default=str), diagnosis_id),
        )
        self._conn.commit()

    def get(self, diagnosis_id: int) -> StoredDiagnosis | None:
        row = self._conn.execute("SELECT * FROM diagnoses WHERE id = ?", (diagnosis_id,)).fetchone()
        if row is None:
            return None
        return _row_to_stored_diagnosis(row)
