---
depends_on:
  - /tasks/listener/alert-classifier.md
---

# Dedup and cooldown

A flapping alert must not produce a diagnosis per flap. Cooldown per
alert fingerprint (class + host + subject): first occurrence gets the
full playbook run; repeats within the window get, at most, a counter
update on the existing thread. In-flight marker persisted so a restart
mid-investigation doesn't double-post. Also the LLM spend guard: an
alert storm is a token storm without this.

## Deliverables

- [x] Fingerprint cooldown window (configurable per class) (commit:
      a2936c0 — `src/dba_agent/cooldown.py`'s `CooldownStore.decide()` +
      `cooldown_for()`; `DEFAULT_COOLDOWN` (30 minutes) with a per-class
      override map (`DEFAULT_CLASS_COOLDOWNS`, `questdb-health-flap` at
      5 minutes) overridable via the constructor's `class_cooldowns`
      param. Reasoning for both the default and the (deliberately
      shorter, not longer) flappy-class override is documented in the
      module's comments above each constant)
- [x] Repeat handling: silent or thread-counter update, never a new
      diagnosis (commit: a2936c0 — `decide()` returns
      `action="cooldown"` with an accumulating `repeat_count` for
      fingerprints seen again inside their window; `should_diagnose` is
      `False` for that case, so a caller can never mistake it for a
      fresh diagnosis. No listener/Slack wiring exists yet to actually
      post the counter update — that's `tasks/poc/e2e-demo.md`'s job —
      this task's job stops at handing back the decision + count)
- [x] Persistent in-flight marker; crash/restart test (commit: a2936c0
      — `start_diagnosis()`/`mark_complete()`/`is_in_flight()` persist
      to the `fingerprint_state` table in a caller-supplied SQLite file
      (`CooldownStore.__init__`'s `db_path` param, defaulting to
      `var/cooldown.sqlite3`, gitignored). Staleness reclaim
      (`DEFAULT_IN_FLIGHT_STALE_AFTER` = 20 minutes) logs a warning via
      `dba_agent`'s configured logger before treating an abandoned
      marker as reclaimable.
      `tests/test_cooldown.py::test_in_flight_marker_survives_a_brand_new_store_instance_same_file`
      is the real crash/restart proof: one `CooldownStore` marks a
      fingerprint in flight and is discarded without `close()` or
      `mark_complete()` (simulated crash), then a brand new instance
      constructed against the same on-disk file sees the marker —
      genuine file-backed SQLite I/O, no mocking, no Docker needed)
- [x] Per-day LLM call budget with loud logging when hit (commit:
      dc288a1 — `try_consume_llm_call()`/`llm_calls_consumed_today()`,
      backed by a second table (`llm_budget`) in the same SQLite file,
      keyed by UTC calendar day so a restart doesn't reset today's
      spend (`DEFAULT_DAILY_LLM_BUDGET` = 200, reasoning in the module).
      Every refusal once the budget is exhausted logs a warning via
      `logging_setup`'s `dba_agent` logger — not just the first one —
      per `docs/security-threat-model.md` M9's remediation ("make
      budget-exhaustion behavior explicit and alerting, not silent"))
