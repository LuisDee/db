from __future__ import annotations

import json
from pathlib import Path

import pytest

from dba_agent.classifier import (
    ALERT_CLASSES,
    SEVERITIES,
    SYSTEM_PROMPT,
    Classification,
    build_prompt,
    classify,
    fingerprint,
    is_actionable,
    parse_classification,
)
from dba_agent.llm import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parents[1]
ALERTS_FIXTURE_PATH = REPO_ROOT / "compose" / "injector" / "fixtures" / "alerts.json"
GOLDEN_CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "classifier-golden-corpus.json"


def _load_alert_texts() -> dict[str, str]:
    alerts = json.loads(ALERTS_FIXTURE_PATH.read_text())
    return {entry["id"]: entry["text"] for entry in alerts}


def _load_golden_corpus() -> list[dict]:
    return json.loads(GOLDEN_CORPUS_PATH.read_text())


ALERT_TEXTS = _load_alert_texts()
GOLDEN_CORPUS = _load_golden_corpus()


def _resolve_text(entry: dict) -> str:
    """Golden-corpus entries reference compose/injector/fixtures/alerts.json
    by id rather than duplicating message text -- one source of truth.
    Adversarial entries aren't in that file, so they carry their own
    "text" field instead.
    """
    if "text" in entry:
        return entry["text"]
    return ALERT_TEXTS[entry["id"]]


# --- prompt construction --------------------------------------------------


def test_build_prompt_delimits_alert_text():
    prompt = build_prompt("some alert text")
    assert "<<<ALERT_TEXT_START>>>" in prompt
    assert "<<<ALERT_TEXT_END>>>" in prompt
    assert "some alert text" in prompt


def test_system_prompt_lists_every_enum_value():
    for alert_class in ALERT_CLASSES:
        assert alert_class in SYSTEM_PROMPT
    for severity in SEVERITIES:
        assert severity in SYSTEM_PROMPT


def test_system_prompt_labels_alert_text_as_untrusted():
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT


# --- parse_classification: defensive parsing -------------------------------


def test_parse_classification_happy_path():
    raw = json.dumps(
        {"alert_class": "filesystem-disk-space", "host": "h1", "subject": "/local", "severity": "critical"}
    )
    assert parse_classification(raw) == {
        "alert_class": "filesystem-disk-space",
        "host": "h1",
        "subject": "/local",
        "severity": "critical",
    }


def test_parse_classification_coerces_out_of_enum_alert_class_to_unknown():
    raw = json.dumps({"alert_class": "do-not-alert", "host": "h1", "subject": None, "severity": "critical"})
    result = parse_classification(raw)
    assert result["alert_class"] == "unknown"


def test_parse_classification_coerces_out_of_enum_severity_to_unknown():
    raw = json.dumps({"alert_class": "unknown", "host": None, "subject": None, "severity": "irrelevant-ignore-this"})
    result = parse_classification(raw)
    assert result["severity"] == "unknown"


def test_parse_classification_handles_malformed_json_without_raising():
    result = parse_classification("not json at all {{{")
    assert result == {"alert_class": "unknown", "host": None, "subject": None, "severity": "unknown"}


def test_parse_classification_handles_missing_fields():
    result = parse_classification(json.dumps({}))
    assert result == {"alert_class": "unknown", "host": None, "subject": None, "severity": "unknown"}


def test_parse_classification_handles_non_object_json_top_level():
    result = parse_classification(json.dumps(["not", "an", "object"]))
    assert result["alert_class"] == "unknown"


def test_parse_classification_ignores_non_string_host_and_subject():
    raw = json.dumps({"alert_class": "unknown", "host": 12345, "subject": {"nested": "obj"}, "severity": "ok"})
    result = parse_classification(raw)
    assert result["host"] is None
    assert result["subject"] is None


def test_parse_classification_treats_blank_strings_as_none():
    raw = json.dumps({"alert_class": "unknown", "host": "   ", "subject": "", "severity": "ok"})
    result = parse_classification(raw)
    assert result["host"] is None
    assert result["subject"] is None


# --- fingerprint ------------------------------------------------------------


def test_fingerprint_is_stable_delimited_string():
    assert fingerprint("filesystem-disk-space", "h1", "/local") == "filesystem-disk-space|h1|/local"


def test_fingerprint_uses_placeholder_for_missing_host_and_subject():
    assert fingerprint("unknown", None, None) == "unknown|-|-"


def test_fingerprint_identical_for_questdb_flap_state_flip():
    # qdb-flap-1 (CRITICAL wording) and qdb-flap-2 (OK/recovery wording)
    # describe the same underlying check on the same host -- see
    # fingerprint()'s docstring for why these must collide (cooldown must
    # not re-diagnose a flapping check on every state change).
    fp_critical = fingerprint("questdb-health-flap", "uk01vdb301", None)
    fp_ok = fingerprint("questdb-health-flap", "uk01vdb301", None)
    assert fp_critical == fp_ok


# --- is_actionable -----------------------------------------------------------


@pytest.mark.parametrize("alert_class", ["human-message", "unknown"])
def test_is_actionable_false_for_non_actionable_classes(alert_class):
    classification = Classification(
        alert_class=alert_class, host=None, subject=None, severity="unknown", fingerprint="x"
    )
    assert is_actionable(classification) is False


@pytest.mark.parametrize("alert_class", [c for c in ALERT_CLASSES if c not in ("human-message", "unknown")])
def test_is_actionable_true_for_real_alert_classes(alert_class):
    classification = Classification(
        alert_class=alert_class, host="h", subject=None, severity="critical", fingerprint="x"
    )
    assert is_actionable(classification) is True


# --- classify(): full path with FakeLLMClient -------------------------------


def test_classify_builds_prompt_and_returns_parsed_classification():
    llm = FakeLLMClient(
        responses=[
            json.dumps(
                {"alert_class": "filesystem-disk-space", "host": "h1", "subject": "/local", "severity": "critical"}
            )
        ]
    )

    result = classify("some alert text", llm)

    assert result == Classification(
        alert_class="filesystem-disk-space",
        host="h1",
        subject="/local",
        severity="critical",
        fingerprint="filesystem-disk-space|h1|/local",
    )
    system, prompt = llm.calls[0]
    assert "some alert text" in prompt
    assert system == SYSTEM_PROMPT


def test_classify_never_raises_on_garbage_llm_output():
    llm = FakeLLMClient(responses=["<html>not json</html>"])
    result = classify("whatever", llm)
    assert result.alert_class == "unknown"
    assert result.severity == "unknown"
    assert result.fingerprint == "unknown|-|-"


# --- golden corpus -----------------------------------------------------------
#
# Every entry scripts FakeLLMClient with a specific JSON response (the
# "correctly-labeled" one for the 10 real fixtures and the two
# prompt-injection fixtures; a deliberately out-of-enum one for the
# "adversarial-out-of-enum-response" fixture) and asserts classify() turns
# that into exactly the expected Classification. This proves this
# module's parsing/validation/routing code hits 100% on the corpus --
# it does NOT prove a real LLM resists being steered by the adversarial
# message text; that live-model question is tests/integration/
# test_classifier_live.py's job (skips cleanly without a usable
# ANTHROPIC_API_KEY).


@pytest.mark.parametrize("entry", GOLDEN_CORPUS, ids=[e["id"] for e in GOLDEN_CORPUS])
def test_golden_corpus_entry_classifies_as_expected(entry):
    text = _resolve_text(entry)
    scripted_response = entry.get("llm_response", entry["expected"])
    llm = FakeLLMClient(responses=[json.dumps(scripted_response)])

    result = classify(text, llm)

    expected = entry["expected"]
    assert result.alert_class == expected["alert_class"]
    assert result.host == expected["host"]
    assert result.subject == expected["subject"]
    assert result.severity == expected["severity"]
    assert result.fingerprint == fingerprint(expected["alert_class"], expected["host"], expected["subject"])


def test_golden_corpus_covers_every_alert_class_at_least_once():
    covered = {entry["expected"]["alert_class"] for entry in GOLDEN_CORPUS}
    assert covered == set(ALERT_CLASSES)


def test_golden_corpus_includes_at_least_three_adversarial_entries():
    adversarial_ids = [e["id"] for e in GOLDEN_CORPUS if e["id"].startswith("adversarial-")]
    assert len(adversarial_ids) >= 3


def test_golden_corpus_qdb_flap_fixtures_fingerprint_identically():
    by_id = {e["id"]: e for e in GOLDEN_CORPUS}
    flap1, flap2 = by_id["qdb-flap-1"]["expected"], by_id["qdb-flap-2"]["expected"]
    fp1 = fingerprint(flap1["alert_class"], flap1["host"], flap1["subject"])
    fp2 = fingerprint(flap2["alert_class"], flap2["host"], flap2["subject"])
    assert fp1 == fp2
    assert flap1["severity"] != flap2["severity"]  # different state wording, same fingerprint anyway
