from __future__ import annotations

import json

from dba_agent.classifier import Classification
from dba_agent.executor import EvidenceBundle, QueryResult
from dba_agent.jira_draft import JiraDraft
from dba_agent.llm import FakeLLMClient
from dba_agent.synthesis import (
    SYSTEM_PROMPT,
    Diagnosis,
    build_synthesis_prompt,
    parse_diagnosis,
    render_slack_text,
    should_post,
    synthesize,
)


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


def _ok(name, columns, rows, sql="SELECT 1"):
    return QueryResult(query_name=name, sql=sql, columns=columns, rows=rows, error=None, duration_seconds=0.01)


def _failed(name, error, sql="SELECT 1"):
    return QueryResult(query_name=name, sql=sql, columns=(), rows=None, error=error, duration_seconds=0.01)


def _bundle(*results, playbook_key="filesystem-disk-space", endpoint_key="pg01"):
    return EvidenceBundle(playbook_key=playbook_key, endpoint_key=endpoint_key, results=results)


# --- prompt construction -----------------------------------------------------


def test_build_synthesis_prompt_delimits_evidence_as_data():
    classification = _classification()
    evidence = _bundle(_ok("database_size", ("size_bytes",), ((900_000_000,),)))

    system, user = build_synthesis_prompt(classification, evidence)

    assert system == SYSTEM_PROMPT
    assert "<<<DBA_AGENT_DATA_START>>>" in user
    assert "<<<DBA_AGENT_DATA_END>>>" in user
    assert "database_size" in user
    assert "900000000" in user
    assert "pg01" in user


def test_build_synthesis_prompt_includes_classification_fields():
    classification = _classification(host="dbhost1", subject="/data", severity="warning")
    evidence = _bundle()

    _, user = build_synthesis_prompt(classification, evidence)

    assert "dbhost1" in user
    assert "/data" in user
    assert "warning" in user
    assert "filesystem-disk-space" in user


def test_build_synthesis_prompt_includes_failed_query_error():
    classification = _classification()
    evidence = _bundle(_failed("wal_summary", "statement timeout"))

    _, user = build_synthesis_prompt(classification, evidence)

    assert "wal_summary" in user
    assert "statement timeout" in user


def test_system_prompt_labels_evidence_as_untrusted():
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT


def test_system_prompt_requires_evidence_citation_and_no_speculation():
    assert "cite" in SYSTEM_PROMPT.lower()
    assert "speculat" in SYSTEM_PROMPT.lower()


# --- parse_diagnosis: defensive parsing --------------------------------------


def test_parse_diagnosis_happy_path():
    raw = json.dumps(
        {
            "verdict": "Disk is filling fast, projected full in 3 days.",
            "detail": "database_size shows 900MB and growing per wal_summary.",
            "has_findings": True,
            "owner": "infra",
        }
    )
    diagnosis = parse_diagnosis(raw)
    assert diagnosis.verdict == "Disk is filling fast, projected full in 3 days."
    assert diagnosis.has_findings is True
    assert diagnosis.owner == "infra"
    assert diagnosis.jira_draft is None


def test_parse_diagnosis_handles_malformed_json_without_raising():
    diagnosis = parse_diagnosis("not json at all {{{")
    assert diagnosis.has_findings is False
    assert diagnosis.owner is None
    assert diagnosis.verdict


def test_parse_diagnosis_handles_non_object_json_top_level():
    diagnosis = parse_diagnosis(json.dumps(["not", "an", "object"]))
    assert diagnosis.has_findings is False
    assert diagnosis.owner is None


def test_parse_diagnosis_handles_missing_fields():
    diagnosis = parse_diagnosis(json.dumps({}))
    assert diagnosis.has_findings is False
    assert diagnosis.owner is None
    assert diagnosis.verdict == "Could not synthesize a diagnosis from the model response."


def test_parse_diagnosis_coerces_out_of_enum_owner_to_none():
    raw = json.dumps({"verdict": "v", "detail": "d", "has_findings": True, "owner": "some-other-team"})
    diagnosis = parse_diagnosis(raw)
    assert diagnosis.owner is None


def test_parse_diagnosis_coerces_non_bool_has_findings_to_false():
    raw = json.dumps({"verdict": "v", "detail": "d", "has_findings": "yes", "owner": None})
    diagnosis = parse_diagnosis(raw)
    assert diagnosis.has_findings is False


def test_parse_diagnosis_ignores_non_string_verdict_and_detail():
    raw = json.dumps({"verdict": 12345, "detail": {"nested": "obj"}, "has_findings": True, "owner": "db"})
    diagnosis = parse_diagnosis(raw)
    assert diagnosis.verdict == "Could not synthesize a diagnosis from the model response."
    assert diagnosis.has_findings is False


def test_parse_diagnosis_nothing_to_add_response():
    raw = json.dumps(
        {
            "verdict": "Nothing beyond what the alert already reported.",
            "detail": "All queries succeeded but show no new signal beyond the alert itself.",
            "has_findings": False,
            "owner": None,
        }
    )
    diagnosis = parse_diagnosis(raw)
    assert diagnosis.has_findings is False
    assert should_post(diagnosis) is False


# --- synthesize(): full path with FakeLLMClient ------------------------------


def test_synthesize_returns_parsed_diagnosis_and_uses_the_prompt():
    llm = FakeLLMClient(
        responses=[
            json.dumps(
                {
                    "verdict": "Growth confirmed by wal_summary.",
                    "detail": "database_size shows steady growth.",
                    "has_findings": True,
                    "owner": "db",
                }
            )
        ]
    )
    classification = _classification()
    evidence = _bundle(_ok("database_size", ("size_bytes",), ((1,),)))

    diagnosis = synthesize(classification, evidence, llm)

    assert diagnosis.verdict == "Growth confirmed by wal_summary."
    assert diagnosis.owner == "db"
    assert diagnosis.jira_draft is None  # db-owned, not infra -- no Jira draft attached
    system, user = llm.calls[0]
    assert system == SYSTEM_PROMPT
    assert "database_size" in user


def test_synthesize_attaches_jira_draft_when_infra_owned_with_findings():
    llm = FakeLLMClient(
        responses=[
            json.dumps(
                {
                    "verdict": "Filesystem filling fast.",
                    "detail": "database_size shows 900MB, per database_size query.",
                    "has_findings": True,
                    "owner": "infra",
                }
            )
        ]
    )
    classification = _classification(host="pg01", subject="/pgdata")
    evidence = _bundle(_ok("database_size", ("size_bytes",), ((900_000_000,),)))

    diagnosis = synthesize(classification, evidence, llm)

    assert diagnosis.jira_draft is not None
    assert isinstance(diagnosis.jira_draft, JiraDraft)
    assert "pg01" in diagnosis.jira_draft.title
    assert "/pgdata" in diagnosis.jira_draft.title


def test_synthesize_does_not_attach_jira_draft_when_no_findings_even_if_infra():
    llm = FakeLLMClient(
        responses=[
            json.dumps(
                {
                    "verdict": "Nothing new here.",
                    "detail": "",
                    "has_findings": False,
                    "owner": "infra",
                }
            )
        ]
    )
    diagnosis = synthesize(_classification(), _bundle(), llm)
    assert diagnosis.jira_draft is None


def test_synthesize_never_raises_on_garbage_llm_output():
    llm = FakeLLMClient(responses=["<html>not json</html>"])
    diagnosis = synthesize(_classification(), _bundle(), llm)
    assert diagnosis.has_findings is False
    assert diagnosis.jira_draft is None


# --- should_post --------------------------------------------------------------


def test_should_post_true_when_has_findings():
    diagnosis = Diagnosis(verdict="v", detail="d", has_findings=True)
    assert should_post(diagnosis) is True


def test_should_post_false_when_no_findings():
    diagnosis = Diagnosis(verdict="v", detail="d", has_findings=False)
    assert should_post(diagnosis) is False


# --- render_slack_text --------------------------------------------------------


def test_render_slack_text_puts_verdict_first_and_bold():
    diagnosis = Diagnosis(verdict="Disk filling fast.", detail="details here", has_findings=True)
    text = render_slack_text(diagnosis)
    lines = text.splitlines()
    assert lines[0] == "*Disk filling fast.*"
    assert "details here" in text
    assert text.index("Disk filling fast.") < text.index("details here")


def test_render_slack_text_omits_detail_section_when_blank():
    diagnosis = Diagnosis(verdict="Nothing new.", detail="", has_findings=False)
    text = render_slack_text(diagnosis)
    assert text == "*Nothing new.*"


def test_render_slack_text_includes_jira_draft_when_present():
    draft = JiraDraft(title="[infra] Disk space growth on pg01:/pgdata", body="body text")
    diagnosis = Diagnosis(verdict="v", detail="d", has_findings=True, owner="infra", jira_draft=draft)
    text = render_slack_text(diagnosis)
    assert draft.title in text
    assert draft.body in text
