"""Runs the classifier's golden corpus against the real Anthropic API.

Everything in tests/test_classifier.py proves parsing/validation/routing
against a *scripted* FakeLLMClient -- it says nothing about whether an
actual model, given the real prompt, gets the labels right or resists the
adversarial entries. This file is that missing proof, using the same
corpus (tests/fixtures/classifier-golden-corpus.json) so there is exactly
one place the expected labels live.

Marked `llm_live`, not `integration`: this needs a real, billed call to
api.anthropic.com, not a local/testcontainers database engine -- a
genuinely different gating condition (external network + a per-run cost)
from the Docker-or-skip semantics `integration` already has, hence the
new marker registered in pyproject.toml rather than overloading
`integration`. Same "skip cleanly, never error" contract as the DB
integration tests (tests/integration/README.md): no usable
ANTHROPIC_API_KEY -> SKIPPED with a reason, not a failure. Confirmed
skipping in this sandbox (no usable key here); this is the file to run
by hand ("run on demand, not in CI", per tasks/listener/
alert-classifier.md) once a real key is available.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dba_agent.classifier import classify, fingerprint
from dba_agent.llm import AnthropicLLMClient

pytestmark = pytest.mark.llm_live

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERTS_FIXTURE_PATH = REPO_ROOT / "compose" / "injector" / "fixtures" / "alerts.json"
GOLDEN_CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "classifier-golden-corpus.json"

# A live model asked to resist a crafted injection is not expected to be
# perfect where a deterministic parser is -- this is a judgement-quality
# bar (docstring above), not the 100%-on-scripted-fakes bar the unit
# suite already enforces exactly.
MIN_ACCURACY = 0.9


def _load_alert_texts() -> dict[str, str]:
    alerts = json.loads(ALERTS_FIXTURE_PATH.read_text())
    return {entry["id"]: entry["text"] for entry in alerts}


def _resolve_text(entry: dict, alert_texts: dict[str, str]) -> str:
    if "text" in entry:
        return entry["text"]
    return alert_texts[entry["id"]]


@pytest.fixture(scope="session")
def anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set -- skipping live classifier accuracy test")
    return key


def test_golden_corpus_accuracy_against_the_real_llm(anthropic_api_key):
    llm = AnthropicLLMClient(api_key=anthropic_api_key)
    alert_texts = _load_alert_texts()
    corpus = json.loads(GOLDEN_CORPUS_PATH.read_text())

    failures = []
    for entry in corpus:
        text = _resolve_text(entry, alert_texts)
        expected = entry["expected"]
        result = classify(text, llm)

        expected_fingerprint = fingerprint(expected["alert_class"], expected["host"], expected["subject"])
        ok = (
            result.alert_class == expected["alert_class"]
            and result.host == expected["host"]
            and result.subject == expected["subject"]
            and result.severity == expected["severity"]
            and result.fingerprint == expected_fingerprint
        )
        if not ok:
            failures.append((entry["id"], expected, result))

    accuracy = 1 - (len(failures) / len(corpus))
    assert accuracy >= MIN_ACCURACY, (
        f"live classifier accuracy {accuracy:.0%} below {MIN_ACCURACY:.0%} threshold; "
        f"failures: {failures}"
    )
