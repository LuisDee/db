---
depends_on:
  - /tasks/foundation/compose-stack.md
  - /tasks/foundation/endpoint-registry.md
  - /tasks/playbooks/playbook-framework.md
---

# v0 POC-ready — outstanding blockers

Everything that must clear before `tasks/poc/e2e-demo.md` can actually
run as a demonstrable end-to-end loop in the local compose stack. These
are gaps a hands-on stress test of the live stack (2026-07-08) surfaced:
the component tasks are individually `[x]` and their unit tests pass, but
the pieces have never been wired or run together against live engines, so
the demo's own preconditions are not yet met.

`tasks/README.md` optimistically called the remaining POC work "pure
integration/wiring — every direct dependency done." The run below
disproves that: the read path cannot connect to the stack it ships with,
and `make up` does not bring the stack up cleanly. Each item is a
prerequisite of `poc/e2e-demo`, not a nice-to-have.

Evidence and severities: the 2026-07-08 live stress test + adversarial
review (190/190 unit tests pass; 12/17 integration tests pass against the
live stack; the 5 failures all trace to the two blockers below).

## Deliverables

- [ ] **`dba_agent_ro` provisioning SQL exists and `make up` creates it.**
      The read path hardcodes `user=dba_agent_ro` (`executor.py:18`) but
      no seed/init/provisioning file creates that role anywhere — a fresh
      `make up` has only `postgres` + `replicator`. Proven live: the real
      `PostgresRunner` + disk-space playbook fails with
      `connection ... failed` until the role is hand-created; after
      creating it (pg_monitor + SELECT on app), the same playbook returns
      real evidence. Add `compose/postgres/init/*_dba_agent_ro.sql`
      (pg_monitor + pg_read_all_stats + pg_read_all_settings + USAGE/
      SELECT on `app`) and an Oracle init user (`CREATE SESSION` +
      `SELECT_CATALOG_ROLE`, per spec §6), idempotent, password sourced
      from `compose/.env` and matching the registry `credential_ref`.
      (QuestDB reads are unauthenticated and already work live.)

- [ ] **`make up` brings the FULL stack up cleanly, including
      `postgres-replica`.** Today `make up` exits non-zero: `--wait`
      aborts the whole bring-up when postgres is briefly slow to report
      healthy under Oracle's boot load, leaving `postgres-replica` in
      `Created` (never started) — the standby the replication-lag
      playbook targets. Fixed host port `5433` also collides with a
      native local Postgres on a dev machine. Fix the dependency/wait
      ordering (or postgres `start_period`), and make the published host
      ports overridable so a dev box with its own Postgres can still
      `make up`.

- [ ] **The orchestrator/dispatcher is built** — the code that chains
      alert → `classify()` → `registry.resolve()` (treat
      `UnknownEndpointError` as a first-class "unknown host, do nothing")
      → `run_playbook()` → `synthesize()` → cooldown decision → post.
      Restated here because nothing wires it today (grep confirms
      `classify()`/`run_playbook()`/`synthesize()` are never chained in
      `src/`, and `app.py` only runs a `/healthz` server). This is the
      core of `poc/e2e-demo` — the demo cannot exist without it.

- [ ] **Host → Check_MK base-URL resolution, or an explicit decision to
      scope the demo without it.** `synthesize()` can attach a
      time-to-full estimate + Jira draft only if given a `CheckMkClient`,
      but no code resolves a host to a Check_MK site URL (the registry
      carries DB endpoints only; `synthesis.py`'s own docstring flags
      this as e2e-demo's job). Either add the resolution, or decide the
      v0 disk-space demo runs SQL-evidence-only and defer the Check_MK
      enrichment to v1 — and record which.

- [ ] **Fix the JSON log formatter escaping** (`logging_setup.py:31-34`).
      `%(message)s` is spliced into a hand-built JSON string with no
      escaping, so any log line containing a `"` or newline (e.g. an
      alert subject) emits invalid JSON — a demo whose logs don't parse
      is a bad look. Serialise the record with `json.dumps({...})`.

- [ ] **Wire config so the running container is configurable**
      (`app.py:13` calls `load_config()` with no `yaml_path`, so
      `log_level`/`environment` are pinned to `INFO`/`development` with no
      override path). Add `LOG_LEVEL`/`ENV` env fallbacks so DEBUG can be
      turned on for the demo.

- [ ] **Injector fixture `type` slugs match the classifier's
      `ALERT_CLASSES`** (or the mapping is documented). Fixtures use
      `disk-space` / `replication-lag` / `human`; the classifier emits
      `filesystem-disk-space` / `standby-replication-lag` /
      `human-message`. Harmless while nothing joins them; a silent
      mis-join the moment the e2e loop keys off the class.

- [ ] **`pytest -m integration` is green against the `make up` stack.**
      Today the Oracle test hardcodes password `test` (the testcontainer
      default) and can't run against compose's `DevOnly_Oracle_Pw1`;
      parametrise the credential so the integration suite passes against
      the same stack the demo uses.

- [ ] **Ride-along POC-era security items** from
      `tasks/security/threat-model-remediation.md` that belong with the
      wiring (host-resolution do-nothing routing; redaction runs BEFORE
      the LLM call; evidence rendered as inert text). Referenced here, not
      duplicated — close them there as the dispatcher lands.
