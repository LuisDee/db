from dba_agent.executor import (
    READ_ONLY_USER,
    EvidenceBundle,
    QueryResult,
    _build_postgres_dsn,
    _statement_timeout_sql,
    run_playbook,
)
from dba_agent.playbooks import Playbook, PlaybookQuery
from dba_agent.registry import Endpoint


class FakeRunner:
    """Scripted engine runner for pure unit tests -- no real DB. Mirrors
    the FakeLLMClient/FakeSlackClient pattern already used elsewhere.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, endpoint, query, timeout_seconds):
        self.calls.append((endpoint.key, query.name, timeout_seconds))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _endpoint(engine="postgres"):
    return Endpoint(
        key="test-db",
        engine=engine,
        dsn="host=127.0.0.1 port=5432 dbname=postgres",
        credential_ref="TEST_CRED",
        tier="dev",
    )


def _playbook_with(*queries):
    return Playbook(key="test-playbook", queries={"postgres": tuple(queries)})


def test_build_postgres_dsn_appends_fixed_readonly_user_and_password():
    endpoint = _endpoint()
    dsn = _build_postgres_dsn(endpoint, password="s3cr3t")
    assert dsn == f"host=127.0.0.1 port=5432 dbname=postgres user={READ_ONLY_USER} password=s3cr3t"


def test_statement_timeout_sql_converts_seconds_to_milliseconds():
    assert _statement_timeout_sql(2.5) == "SET statement_timeout = 2500"


def test_run_playbook_produces_evidence_bundle_with_columns_and_rows():
    query = PlaybookQuery(name="row_count", sql="SELECT count(*) FROM app.orders")
    playbook = _playbook_with(query)
    runner = FakeRunner(responses=[(("count",), ((42,),))])

    bundle = run_playbook(playbook, _endpoint(), runner)

    assert isinstance(bundle, EvidenceBundle)
    assert bundle.playbook_key == "test-playbook"
    assert bundle.endpoint_key == "test-db"
    assert len(bundle.results) == 1
    result = bundle.results[0]
    assert isinstance(result, QueryResult)
    assert result.query_name == "row_count"
    assert result.columns == ("count",)
    assert result.rows == ((42,),)
    assert result.error is None
    assert result.succeeded is True


def test_run_playbook_tolerates_partial_failure():
    good = PlaybookQuery(name="good", sql="SELECT 1")
    bad = PlaybookQuery(name="bad", sql="SELECT * FROM does_not_exist")
    playbook = _playbook_with(good, bad)
    runner = FakeRunner(responses=[(("?column?",), ((1,),)), RuntimeError("relation not found")])

    bundle = run_playbook(playbook, _endpoint(), runner)

    assert len(bundle.results) == 2
    assert bundle.results[0].succeeded is True
    assert bundle.results[1].succeeded is False
    assert bundle.results[1].error == "relation not found"
    assert bundle.results[1].rows is None
    # the good query's result must survive the bad one's failure
    assert bundle.any_succeeded is True


def test_run_playbook_stops_at_no_queries_for_unconfigured_engine():
    playbook = Playbook(key="empty-for-oracle", queries={"postgres": (PlaybookQuery("x", "SELECT 1"),)})
    runner = FakeRunner(responses=[])

    bundle = run_playbook(playbook, _endpoint(engine="oracle"), runner)

    assert bundle.results == ()
    assert runner.calls == []


def test_run_playbook_passes_timeout_through_to_runner():
    query = PlaybookQuery(name="q", sql="SELECT 1")
    playbook = _playbook_with(query)
    runner = FakeRunner(responses=[(("?column?",), ((1,),))])

    run_playbook(playbook, _endpoint(), runner, timeout_seconds=3.0)

    assert runner.calls == [("test-db", "q", 3.0)]


def test_run_playbook_redacts_flagged_columns_only():
    query = PlaybookQuery(
        name="recent_queries",
        sql="SELECT query, calls FROM pg_stat_statements",
        redact_columns=("query",),
    )
    playbook = _playbook_with(query)
    runner = FakeRunner(
        responses=[
            (("query", "calls"), (("SELECT * FROM x WHERE id = 42", 7),))
        ]
    )

    bundle = run_playbook(playbook, _endpoint(), runner)

    row = bundle.results[0].rows[0]
    assert row[0] == "SELECT * FROM x WHERE id = ?"  # redacted
    assert row[1] == 7  # untouched -- not a flagged column, and not a string


def test_query_result_duration_is_recorded():
    query = PlaybookQuery(name="q", sql="SELECT 1")
    playbook = _playbook_with(query)
    runner = FakeRunner(responses=[(("?column?",), ((1,),))])

    bundle = run_playbook(playbook, _endpoint(), runner)

    assert bundle.results[0].duration_seconds >= 0.0


class _FakeOracleCursor:
    """Drives OracleRunner.run()'s real code path without a live Oracle
    instance -- closes a gap an adversarial review caught: OracleRunner
    had zero references outside its own definition, so its actual
    control flow (call_timeout conversion, best-effort read-only,
    column/row extraction) had never executed once.
    """

    def __init__(self, rows, column_names, raise_on_sql=None):
        self._rows = rows
        self.description = [(name,) for name in column_names] if column_names else None
        self.executed = []
        self._raise_on_sql = raise_on_sql or {}

    def execute(self, sql):
        self.executed.append(sql)
        if sql in self._raise_on_sql:
            raise self._raise_on_sql[sql]

    def fetchall(self):
        return self._rows


class _FakeOracleConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.call_timeout = None

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_oracle_runner_sets_call_timeout_in_milliseconds(monkeypatch):
    import oracledb

    monkeypatch.setenv("TEST_CRED", "s3cr3t")

    cursor = _FakeOracleCursor(rows=((1,),), column_names=("col",))
    conn = _FakeOracleConnection(cursor)
    monkeypatch.setattr(oracledb, "connect", lambda **kwargs: conn)

    from dba_agent.executor import OracleRunner

    OracleRunner().run(_endpoint(engine="oracle"), PlaybookQuery("q", "SELECT 1 FROM dual"), timeout_seconds=2.5)

    assert conn.call_timeout == 2500


def test_oracle_runner_executes_query_and_extracts_columns_and_rows(monkeypatch):
    import oracledb

    monkeypatch.setenv("TEST_CRED", "s3cr3t")

    cursor = _FakeOracleCursor(rows=((1, "a"), (2, "b")), column_names=("id", "label"))
    monkeypatch.setattr(oracledb, "connect", lambda **kwargs: _FakeOracleConnection(cursor))

    from dba_agent.executor import OracleRunner

    columns, rows = OracleRunner().run(
        _endpoint(engine="oracle"), PlaybookQuery("q", "SELECT id, label FROM t"), timeout_seconds=5.0
    )

    assert columns == ("id", "label")
    assert rows == ((1, "a"), (2, "b"))
    assert "SELECT id, label FROM t" in cursor.executed


def test_oracle_runner_tolerates_read_only_statement_failure(monkeypatch):
    """Best-effort defence in depth (executor.py's own comment): if
    SET TRANSACTION READ ONLY fails (e.g. not the first statement in a
    pooled session), the actual query must still run -- never fatal.
    """
    import oracledb

    monkeypatch.setenv("TEST_CRED", "s3cr3t")

    cursor = _FakeOracleCursor(
        rows=((1,),),
        column_names=("col",),
        raise_on_sql={"SET TRANSACTION READ ONLY": oracledb.Error("not first in transaction")},
    )
    monkeypatch.setattr(oracledb, "connect", lambda **kwargs: _FakeOracleConnection(cursor))

    from dba_agent.executor import OracleRunner

    columns, rows = OracleRunner().run(
        _endpoint(engine="oracle"), PlaybookQuery("q", "SELECT 1 FROM dual"), timeout_seconds=1.0
    )

    assert rows == ((1,),)  # the real query still executed despite the read-only attempt failing
    assert "SELECT 1 FROM dual" in cursor.executed


def test_oracle_runner_does_not_swallow_the_actual_query_failure(monkeypatch):
    import oracledb

    monkeypatch.setenv("TEST_CRED", "s3cr3t")

    cursor = _FakeOracleCursor(
        rows=(), column_names=None, raise_on_sql={"SELECT 1 FROM broken": oracledb.Error("ORA-00942")}
    )
    monkeypatch.setattr(oracledb, "connect", lambda **kwargs: _FakeOracleConnection(cursor))

    from dba_agent.executor import OracleRunner
    import pytest

    with pytest.raises(oracledb.Error, match="ORA-00942"):
        OracleRunner().run(_endpoint(engine="oracle"), PlaybookQuery("q", "SELECT 1 FROM broken"), timeout_seconds=1.0)
