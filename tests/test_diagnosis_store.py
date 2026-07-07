from __future__ import annotations

from dba_agent.classifier import Classification
from dba_agent.diagnosis_store import DiagnosisStore
from dba_agent.executor import EvidenceBundle, QueryResult
from dba_agent.synthesis import Diagnosis, render_slack_text


def _classification(**overrides) -> Classification:
    fields = dict(
        alert_class="filesystem-disk-space",
        host="pg01",
        subject="/pgdata",
        severity="critical",
        fingerprint="filesystem-disk-space|pg01|/pgdata",
    )
    fields.update(overrides)
    return Classification(**fields)


def _bundle(*results) -> EvidenceBundle:
    return EvidenceBundle(playbook_key="filesystem-disk-space", endpoint_key="pg01", results=results)


def _ok(name, columns, rows):
    return QueryResult(query_name=name, sql=f"SELECT ... -- {name}", columns=columns, rows=rows, error=None, duration_seconds=0.01)


def test_record_and_get_round_trip(tmp_path):
    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    classification = _classification()
    evidence = _bundle(_ok("database_size", ("size_bytes",), ((900_000_000,),)))
    diagnosis = Diagnosis(verdict="v", detail="d", has_findings=True, owner="infra")
    reply_text = render_slack_text(diagnosis)

    diagnosis_id = store.record(classification, evidence, diagnosis, reply_text)

    stored = store.get(diagnosis_id)
    assert stored is not None
    assert stored.fingerprint == classification.fingerprint
    assert stored.alert_class == "filesystem-disk-space"
    assert stored.host == "pg01"
    assert stored.subject == "/pgdata"
    assert stored.severity == "critical"
    assert stored.verdict == "v"
    assert stored.detail == "d"
    assert stored.has_findings is True
    assert stored.owner == "infra"
    assert stored.reply_text == reply_text
    assert stored.reactions is None
    assert stored.evidence["playbook_key"] == "filesystem-disk-space"
    assert stored.evidence["results"][0]["query_name"] == "database_size"
    assert stored.evidence["results"][0]["rows"] == [[900_000_000]]


def test_get_returns_none_for_unknown_id(tmp_path):
    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    assert store.get(999) is None


def test_reactions_start_null(tmp_path):
    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    diagnosis_id = store.record(_classification(), _bundle(), Diagnosis(verdict="v", detail="", has_findings=False), "text")
    stored = store.get(diagnosis_id)
    assert stored.reactions is None


def test_update_reactions_is_retrievable(tmp_path):
    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    diagnosis_id = store.record(_classification(), _bundle(), Diagnosis(verdict="v", detail="", has_findings=True), "text")

    store.update_reactions(diagnosis_id, {"thumbsup": 2, "thumbsdown": 0})

    stored = store.get(diagnosis_id)
    assert stored.reactions == {"thumbsup": 2, "thumbsdown": 0}


def test_multiple_diagnoses_get_distinct_ids(tmp_path):
    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    first = store.record(_classification(), _bundle(), Diagnosis(verdict="v1", detail="", has_findings=False), "t1")
    second = store.record(_classification(), _bundle(), Diagnosis(verdict="v2", detail="", has_findings=False), "t2")

    assert first != second
    assert store.get(first).verdict == "v1"
    assert store.get(second).verdict == "v2"


def test_store_persists_across_reopen(tmp_path):
    db_path = tmp_path / "diagnoses.sqlite3"
    store = DiagnosisStore(db_path)
    diagnosis_id = store.record(_classification(), _bundle(), Diagnosis(verdict="v", detail="", has_findings=False), "text")
    store.close()

    reopened = DiagnosisStore(db_path)
    stored = reopened.get(diagnosis_id)
    assert stored is not None
    assert stored.verdict == "v"


def test_failed_query_evidence_serializes_without_raising(tmp_path):
    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    failed = QueryResult(query_name="wal_summary", sql="SELECT 1", columns=(), rows=None, error="timeout", duration_seconds=0.01)
    evidence = _bundle(failed)

    diagnosis_id = store.record(_classification(), evidence, Diagnosis(verdict="v", detail="", has_findings=False), "text")

    stored = store.get(diagnosis_id)
    assert stored.evidence["results"][0]["error"] == "timeout"
    assert stored.evidence["results"][0]["rows"] is None
