"""Proves the missing link between the playbook-framework's real output
and this task's synthesis input: real Postgres -> real load_playbook() ->
real run_playbook() -> a real EvidenceBundle -> synthesize(), using a
FakeLLMClient (scripted, not live) so the LLM half of the proof stays
free/deterministic while the *wiring* half -- does a genuine
EvidenceBundle, shaped exactly the way the executor really produces it,
actually flow into build_synthesis_prompt/parse_diagnosis/synthesize
without blowing up or losing data -- is proven for real.

Mirrors tests/integration/test_playbook_disk_space.py and
test_full_chain_wiring.py's established pattern and docstring style.
Postgres-only here (same rationale those two files already give for
skipping QuestDB/Oracle in this sandbox: no Docker, QuestDB's binary
download is blocked by egress policy, Oracle needs a container this
sandbox can't run). Real, billed LLM synthesis quality is NOT proven
here -- that's tests/integration/test_synthesis_live.py's job (skips
cleanly without ANTHROPIC_API_KEY), same split test_classifier_live.py
already established relative to test_classifier.py's scripted-fake
suite.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dba_agent.classifier import Classification, fingerprint
from dba_agent.diagnosis_store import DiagnosisStore
from dba_agent.executor import PostgresRunner, run_playbook
from dba_agent.llm import FakeLLMClient
from dba_agent.playbooks import load_playbook
from dba_agent.registry import Endpoint
from dba_agent.synthesis import render_slack_text, should_post, synthesize

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK_PATH = REPO_ROOT / "playbooks" / "filesystem-disk-space.yaml"


def _postgres_endpoint(dsn: str) -> Endpoint:
    # Same dance test_playbook_disk_space.py's own _postgres_endpoint uses:
    # the fixture's dsn carries user/password for its own connectivity
    # check; strip that back out so what reaches PostgresRunner is
    # registry-shaped (host/port/db only), with dba_agent_ro + the
    # resolved credential appended by the real code path.
    os.environ["SYNTHESIS_IT_PG_CRED"] = "test"
    base_dsn = dsn.split(" user=")[0]
    return Endpoint(
        key="it-synthesis-postgres",
        engine="postgres",
        dsn=base_dsn,
        credential_ref="SYNTHESIS_IT_PG_CRED",
        tier="dev",
    )


def test_real_evidence_bundle_feeds_synthesize_end_to_end(postgres_dsn):
    playbook = load_playbook(PLAYBOOK_PATH)
    endpoint = _postgres_endpoint(postgres_dsn)

    # Real chain: real playbook file, real executor, real seeded database
    # (compose/postgres/init/03_schema_seed.sql's app.event_log/app.orders).
    evidence = run_playbook(playbook, endpoint, PostgresRunner())
    assert evidence.any_succeeded
    assert len(evidence.results) == 3
    for result in evidence.results:
        assert result.succeeded, result.error

    classification = Classification(
        alert_class="filesystem-disk-space",
        host="it-synthesis-postgres",
        subject="/pgdata",
        severity="critical",
        fingerprint=fingerprint("filesystem-disk-space", "it-synthesis-postgres", "/pgdata"),
    )

    scripted_response = json.dumps(
        {
            "verdict": "Disk usage on it-synthesis-postgres is growing, driven by app.event_log.",
            "detail": (
                "database_size shows a non-trivial database size, and largest_relations "
                "identifies app.event_log as one of the largest relations -- consistent "
                "with an ever-growing log table."
            ),
            "has_findings": True,
            "owner": "db",
        }
    )
    llm = FakeLLMClient(responses=[scripted_response])

    diagnosis = synthesize(classification, evidence, llm)

    # The real evidence actually reached the prompt -- not a stand-in.
    system, user = llm.calls[0]
    assert "database_size" in user
    assert "largest_relations" in user
    assert "wal_summary" in user
    assert "it-synthesis-postgres" in user

    assert diagnosis.has_findings is True
    assert diagnosis.owner == "db"
    assert diagnosis.jira_draft is None  # db-owned, not infra -- no Jira draft attached
    assert should_post(diagnosis) is True

    reply_text = render_slack_text(diagnosis)
    assert "app.event_log" in reply_text


def test_real_evidence_bundle_persists_through_diagnosis_store(postgres_dsn, tmp_path):
    playbook = load_playbook(PLAYBOOK_PATH)
    endpoint = _postgres_endpoint(postgres_dsn)
    evidence = run_playbook(playbook, endpoint, PostgresRunner())

    classification = Classification(
        alert_class="filesystem-disk-space",
        host="it-synthesis-postgres",
        subject="/pgdata",
        severity="critical",
        fingerprint=fingerprint("filesystem-disk-space", "it-synthesis-postgres", "/pgdata"),
    )
    llm = FakeLLMClient(
        responses=[
            json.dumps(
                {
                    "verdict": "Nothing beyond what the alert already said.",
                    "detail": "",
                    "has_findings": False,
                    "owner": None,
                }
            )
        ]
    )

    diagnosis = synthesize(classification, evidence, llm)
    assert should_post(diagnosis) is False  # noise-discipline: caller would suppress this

    store = DiagnosisStore(tmp_path / "diagnoses.sqlite3")
    reply_text = render_slack_text(diagnosis)
    diagnosis_id = store.record(classification, evidence, diagnosis, reply_text)

    stored = store.get(diagnosis_id)
    assert stored is not None
    assert stored.has_findings is False
    assert stored.evidence["results"][0]["query_name"] == "database_size"
    assert stored.reactions is None
