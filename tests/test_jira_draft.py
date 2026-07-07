from datetime import timedelta

from dba_agent.capacity import CapacityEstimate
from dba_agent.executor import EvidenceBundle, QueryResult
from dba_agent.jira_draft import JiraDraft, build_jira_draft


def _bundle(*results: QueryResult) -> EvidenceBundle:
    return EvidenceBundle(playbook_key="filesystem-disk-space", endpoint_key="questdb01", results=results)


def _ok(name, columns, rows):
    return QueryResult(query_name=name, sql=f"SELECT ... -- {name}", columns=columns, rows=rows, error=None, duration_seconds=0.01)


def _failed(name, error):
    return QueryResult(query_name=name, sql=f"SELECT ... -- {name}", columns=(), rows=None, error=error, duration_seconds=0.01)


def test_build_jira_draft_returns_title_and_body():
    draft = build_jira_draft(
        host="questdb01",
        mountpoint="/quest",
        owner="infra",
        evidence=_bundle(_ok("table_storage_summary", ("tableName", "diskSize"), ((("metrics", 900_000_000),)))),
        estimate=None,
    )
    assert isinstance(draft, JiraDraft)
    assert isinstance(draft.title, str)
    assert isinstance(draft.body, str)


def test_title_includes_host_mountpoint_and_owner_tag():
    draft = build_jira_draft(
        host="questdb01", mountpoint="/quest", owner="infra", evidence=_bundle(), estimate=None
    )
    assert "questdb01" in draft.title
    assert "/quest" in draft.title
    assert "infra" in draft.title.lower()


def test_body_includes_evidence_rows_for_successful_queries():
    evidence = _bundle(
        _ok("table_storage_summary", ("tableName", "diskSize"), (("metrics", 900_000_000),)),
    )
    draft = build_jira_draft(host="questdb01", mountpoint="/quest", owner="infra", evidence=evidence, estimate=None)

    assert "table_storage_summary" in draft.body
    assert "metrics" in draft.body
    assert "900000000" in draft.body or "900,000,000" in draft.body


def test_body_notes_failed_queries_without_crashing():
    evidence = _bundle(_failed("wal_summary", "timeout"))
    draft = build_jira_draft(host="pg01", mountpoint="/pgdata", owner="db", evidence=evidence, estimate=None)

    assert "wal_summary" in draft.body
    assert "timeout" in draft.body


def test_body_reports_time_to_full_when_estimate_present():
    estimate = CapacityEstimate(growth_per_second=100.0, time_to_full=timedelta(days=3, hours=6))
    draft = build_jira_draft(host="questdb01", mountpoint="/quest", owner="infra", evidence=_bundle(), estimate=estimate)

    assert "3 day" in draft.body
    assert "growth" in draft.body.lower()


def test_body_reports_no_estimate_when_estimate_is_none():
    draft = build_jira_draft(host="questdb01", mountpoint="/quest", owner="infra", evidence=_bundle(), estimate=None)
    assert "time-to-full" in draft.body.lower() or "time to full" in draft.body.lower()
    assert "not available" in draft.body.lower() or "insufficient" in draft.body.lower()


def test_body_reports_no_estimate_when_flat_growth():
    estimate = CapacityEstimate(growth_per_second=0.0, time_to_full=None)
    draft = build_jira_draft(host="questdb01", mountpoint="/quest", owner="infra", evidence=_bundle(), estimate=estimate)
    assert "not growing" in draft.body.lower() or "no meaningful growth" in draft.body.lower()


def test_suggested_action_differs_by_owner():
    infra_draft = build_jira_draft(host="h", mountpoint="/m", owner="infra", evidence=_bundle(), estimate=None)
    db_draft = build_jira_draft(host="h", mountpoint="/m", owner="db", evidence=_bundle(), estimate=None)

    assert infra_draft.body != db_draft.body
    assert "filesystem" in infra_draft.body.lower() or "volume" in infra_draft.body.lower()
    assert "table" in db_draft.body.lower() or "database" in db_draft.body.lower()
