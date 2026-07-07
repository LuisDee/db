from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dba_agent.cooldown import (
    DEFAULT_CLASS_COOLDOWNS,
    DEFAULT_COOLDOWN,
    CooldownDecision,
    CooldownStore,
)

T0 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


def make_store(tmp_path: Path, **kwargs) -> CooldownStore:
    return CooldownStore(tmp_path / "cooldown.sqlite3", **kwargs)


# --- fingerprint cooldown window ---------------------------------------


def test_never_seen_fingerprint_is_fresh(tmp_path: Path):
    store = make_store(tmp_path)

    decision = store.decide("filesystem-disk-space|host1|/quest", "filesystem-disk-space", now=T0)

    assert decision.should_diagnose
    assert decision.action == "diagnose"
    assert decision.repeat_count == 1


def test_repeat_within_window_is_not_a_fresh_diagnosis(tmp_path: Path):
    store = make_store(tmp_path)
    fp = "filesystem-disk-space|host1|/quest"
    store.start_diagnosis(fp, "filesystem-disk-space", now=T0)
    store.mark_complete(fp)

    decision = store.decide(fp, "filesystem-disk-space", now=T0 + timedelta(minutes=5))

    assert not decision.should_diagnose
    assert decision.action == "cooldown"
    assert decision.repeat_count == 1


def test_repeat_count_accumulates_across_multiple_flaps(tmp_path: Path):
    store = make_store(tmp_path)
    fp = "questdb-health-flap|qdb1|health"
    store.start_diagnosis(fp, "questdb-health-flap", now=T0)
    store.mark_complete(fp)

    d1 = store.decide(fp, "questdb-health-flap", now=T0 + timedelta(minutes=1))
    d2 = store.decide(fp, "questdb-health-flap", now=T0 + timedelta(minutes=2))
    d3 = store.decide(fp, "questdb-health-flap", now=T0 + timedelta(minutes=3))

    assert [d1.repeat_count, d2.repeat_count, d3.repeat_count] == [1, 2, 3]
    assert all(not d.should_diagnose for d in (d1, d2, d3))


def test_fingerprint_is_fresh_again_once_cooldown_expires(tmp_path: Path):
    store = make_store(tmp_path)
    fp = "filesystem-disk-space|host1|/quest"
    store.start_diagnosis(fp, "filesystem-disk-space", now=T0)
    store.mark_complete(fp)

    decision = store.decide(
        fp, "filesystem-disk-space", now=T0 + DEFAULT_COOLDOWN + timedelta(seconds=1)
    )

    assert decision.should_diagnose
    assert decision.action == "diagnose"


def test_default_cooldown_is_thirty_minutes():
    assert DEFAULT_COOLDOWN == timedelta(minutes=30)


def test_questdb_health_flap_has_a_shorter_configured_cooldown():
    assert DEFAULT_CLASS_COOLDOWNS["questdb-health-flap"] < DEFAULT_COOLDOWN


def test_cooldown_for_unconfigured_class_falls_back_to_default(tmp_path: Path):
    store = make_store(tmp_path)

    assert store.cooldown_for("tablespace-usage") == DEFAULT_COOLDOWN


def test_cooldown_for_configured_class_uses_the_override(tmp_path: Path):
    store = make_store(tmp_path)

    assert store.cooldown_for("questdb-health-flap") == DEFAULT_CLASS_COOLDOWNS["questdb-health-flap"]


def test_per_class_cooldown_can_be_overridden_via_constructor(tmp_path: Path):
    store = make_store(tmp_path, class_cooldowns={"tablespace-usage": timedelta(minutes=1)})

    assert store.cooldown_for("tablespace-usage") == timedelta(minutes=1)
    # unrelated defaults are untouched
    assert store.cooldown_for("questdb-health-flap") == DEFAULT_CLASS_COOLDOWNS["questdb-health-flap"]


def test_different_fingerprints_do_not_interfere(tmp_path: Path):
    store = make_store(tmp_path)
    fp_a = "filesystem-disk-space|host1|/quest"
    fp_b = "filesystem-disk-space|host2|/quest"
    store.start_diagnosis(fp_a, "filesystem-disk-space", now=T0)
    store.mark_complete(fp_a)

    decision = store.decide(fp_b, "filesystem-disk-space", now=T0 + timedelta(minutes=1))

    assert decision.should_diagnose


# --- persistent in-flight marker + crash/restart -----------------------


def test_start_diagnosis_marks_fingerprint_in_flight(tmp_path: Path):
    store = make_store(tmp_path)
    fp = "tablespace-usage|host1|USER_INDEX_04"

    store.start_diagnosis(fp, "tablespace-usage", now=T0)

    assert store.is_in_flight(fp, now=T0 + timedelta(seconds=1))


def test_in_flight_fingerprint_refuses_a_concurrent_second_run(tmp_path: Path):
    store = make_store(tmp_path)
    fp = "tablespace-usage|host1|USER_INDEX_04"
    store.start_diagnosis(fp, "tablespace-usage", now=T0)

    decision = store.decide(fp, "tablespace-usage", now=T0 + timedelta(seconds=30))

    assert not decision.should_diagnose
    assert decision.action == "in_flight"


def test_mark_complete_clears_in_flight_and_starts_cooldown(tmp_path: Path):
    store = make_store(tmp_path)
    fp = "tablespace-usage|host1|USER_INDEX_04"
    store.start_diagnosis(fp, "tablespace-usage", now=T0)

    store.mark_complete(fp)

    assert not store.is_in_flight(fp, now=T0 + timedelta(seconds=1))
    decision = store.decide(fp, "tablespace-usage", now=T0 + timedelta(seconds=2))
    assert decision.action == "cooldown"


def test_in_flight_marker_survives_a_brand_new_store_instance_same_file(tmp_path: Path):
    """Genuine crash/restart proof: no mocking -- real SQLite file I/O.
    Process 1 marks a fingerprint in flight and (simulating a crash)
    never calls mark_complete or even close(). Process 2 is a totally
    separate CooldownStore instance constructed fresh against the same
    on-disk file, and must see the in-flight marker.
    """
    db_path = tmp_path / "cooldown.sqlite3"
    fp = "standby-replication-lag|boproddb-prod|apply-lag"

    store_process_1 = CooldownStore(db_path)
    store_process_1.start_diagnosis(fp, "standby-replication-lag", now=T0)
    # No mark_complete(), no close() -- simulating a hard crash mid-run.
    del store_process_1

    store_process_2 = CooldownStore(db_path)
    decision = store_process_2.decide(
        fp, "standby-replication-lag", now=T0 + timedelta(minutes=1)
    )

    assert store_process_2.is_in_flight(fp, now=T0 + timedelta(minutes=1))
    assert decision.action == "in_flight"
    assert not decision.should_diagnose


def test_stale_in_flight_marker_is_reclaimed_after_timeout(tmp_path: Path):
    store = make_store(tmp_path, in_flight_stale_after=timedelta(minutes=20))
    fp = "tablespace-usage|host1|USER_INDEX_04"
    store.start_diagnosis(fp, "tablespace-usage", now=T0)

    decision = store.decide(
        fp, "tablespace-usage", now=T0 + timedelta(minutes=21)
    )

    assert decision.should_diagnose
    assert decision.action == "diagnose"


def test_reclaiming_a_stale_in_flight_marker_logs_a_warning(tmp_path: Path, caplog):
    store = make_store(tmp_path, in_flight_stale_after=timedelta(minutes=20))
    fp = "tablespace-usage|host1|USER_INDEX_04"
    store.start_diagnosis(fp, "tablespace-usage", now=T0)

    with caplog.at_level("WARNING", logger="dba_agent"):
        store.decide(fp, "tablespace-usage", now=T0 + timedelta(minutes=25))

    assert any("stale in-flight" in record.message for record in caplog.records)


def test_reclaimed_stale_marker_allows_a_fresh_run_to_start_and_persist(tmp_path: Path):
    """After reclaim, the caller starts a brand new diagnosis; it must
    persist normally (not somehow stuck on the old marker)."""
    store = make_store(tmp_path, in_flight_stale_after=timedelta(minutes=20))
    fp = "tablespace-usage|host1|USER_INDEX_04"
    store.start_diagnosis(fp, "tablespace-usage", now=T0)

    reclaim_time = T0 + timedelta(minutes=25)
    decision = store.decide(fp, "tablespace-usage", now=reclaim_time)
    assert decision.action == "diagnose"

    store.start_diagnosis(fp, "tablespace-usage", now=reclaim_time)
    assert store.is_in_flight(fp, now=reclaim_time + timedelta(seconds=1))

    store.mark_complete(fp)
    assert not store.is_in_flight(fp, now=reclaim_time + timedelta(seconds=2))


# --- per-day LLM call budget --------------------------------------------


def test_try_consume_allows_calls_within_budget(tmp_path: Path):
    store = make_store(tmp_path, daily_llm_budget=3)

    assert store.try_consume_llm_call(now=T0) is True
    assert store.try_consume_llm_call(now=T0) is True
    assert store.try_consume_llm_call(now=T0) is True
    assert store.llm_calls_consumed_today(now=T0) == 3


def test_try_consume_refuses_once_budget_is_exhausted(tmp_path: Path):
    store = make_store(tmp_path, daily_llm_budget=2)
    store.try_consume_llm_call(now=T0)
    store.try_consume_llm_call(now=T0)

    assert store.try_consume_llm_call(now=T0) is False


def test_budget_refusal_logs_a_loud_warning_every_time(tmp_path: Path, caplog):
    store = make_store(tmp_path, daily_llm_budget=1)
    store.try_consume_llm_call(now=T0)

    with caplog.at_level("WARNING", logger="dba_agent"):
        store.try_consume_llm_call(now=T0)
        store.try_consume_llm_call(now=T0)

    budget_warnings = [r for r in caplog.records if "budget exhausted" in r.message]
    assert len(budget_warnings) == 2  # every refusal logs, not just the first


def test_budget_resets_on_a_new_utc_calendar_day(tmp_path: Path):
    store = make_store(tmp_path, daily_llm_budget=1)
    store.try_consume_llm_call(now=T0)
    assert store.try_consume_llm_call(now=T0) is False

    next_day = T0 + timedelta(days=1)
    assert store.try_consume_llm_call(now=next_day) is True


def test_budget_survives_a_brand_new_store_instance_same_file(tmp_path: Path):
    """A restart must not silently reset today's spend."""
    db_path = tmp_path / "cooldown.sqlite3"
    store_process_1 = CooldownStore(db_path, daily_llm_budget=2)
    store_process_1.try_consume_llm_call(now=T0)
    del store_process_1

    store_process_2 = CooldownStore(db_path, daily_llm_budget=2)
    assert store_process_2.llm_calls_consumed_today(now=T0) == 1
    assert store_process_2.try_consume_llm_call(now=T0) is True
    assert store_process_2.try_consume_llm_call(now=T0) is False


def test_try_consume_can_spend_more_than_one_at_once(tmp_path: Path):
    store = make_store(tmp_path, daily_llm_budget=5)

    assert store.try_consume_llm_call(now=T0, n=3) is True
    assert store.llm_calls_consumed_today(now=T0) == 3
    assert store.try_consume_llm_call(now=T0, n=3) is False  # would exceed budget
    assert store.llm_calls_consumed_today(now=T0) == 3  # refused spend is not recorded


def test_default_daily_llm_budget_is_a_positive_sensible_number(tmp_path: Path):
    store = make_store(tmp_path)

    assert store.try_consume_llm_call(now=T0) is True


# --- misc ----------------------------------------------------------------


def test_decision_is_a_frozen_dataclass_with_expected_fields(tmp_path: Path):
    store = make_store(tmp_path)
    decision = store.decide("some|host|thing", "unknown", now=T0)

    assert isinstance(decision, CooldownDecision)
    with pytest.raises(AttributeError):
        decision.action = "diagnose"  # type: ignore[misc]


def test_constructor_creates_parent_directory_for_db_path(tmp_path: Path):
    nested = tmp_path / "nested" / "dir" / "cooldown.sqlite3"

    store = CooldownStore(nested)

    assert nested.exists()
    assert nested.parent.is_dir()
    store.close()
