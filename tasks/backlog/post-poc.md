# Post-POC backlog — implement after the v0 demo passes

The single "later" home for everything that is NOT required for the
demonstrable v0 POC (`tasks/poc/v0-poc-ready.md` → `tasks/poc/e2e-demo.md`).
Nothing here blocks the compose-stack demo; it is the ordered work after
the loop is proven locally. Where an item is already tracked, this file
points at that tracker rather than restating it (per deferral discipline —
duplicate issues are noise).

Delivery stages mirror `docs/dba-agent-spec.md` §8.

## v1 — plug the proven loop into real infrastructure

- Real Slack channel + Socket-Mode listener → `tasks/listener/slack-listener.md`
  (already specced; NOT on the v0 critical path — the injector drives the
  demo without live Slack).
- Read-only identities on the real target DBs (the productionised form of
  the v0 `dba_agent_ro` compose seed) — hardening tracked under
  `tasks/security/threat-model-remediation.md` "RO credential hardened +
  network-scoped + rotated [H5/M3]".
- Live Check_MK API + **verify `checkmk.py`'s inferred shape** against a
  real instance. The whole request/response shape (REST 1.0 auth header,
  and especially the `filesystem_history` metric endpoint) is currently a
  best-effort reconstruction, never tested live — `docs/dba-agent-spec.md`
  open question 2.
- Weekly noise digest → `tasks/digest/noise-digest.md`.
- Remaining POC playbooks proven against live engines →
  `tasks/playbooks/playbook-replication-lag.md`,
  `tasks/playbooks/playbook-tablespace-usage.md`.

## Hardening surfaced by the 2026-07-08 adversarial review (deferred)

Real defects, but all latent — they sit on the loop/write path that does
not run today, so none block the demo. File:line references are to the
2026-07-08 review. Address each at the seam noted.

- **Cooldown concurrency** (`cooldown.py:230-369`): `decide()`→
  `start_diagnosis()` is check-then-act (TOCTOU → double-diagnose); the
  single `sqlite3` connection is `check_same_thread=True` (crashes from a
  worker thread); `try_consume_llm_call` is a SELECT-then-absolute-UPDATE
  lost-update. Harmless while the demo drives the loop synchronously —
  **fix at the `slack-listener` async seam** with an atomic
  `INSERT ... ON CONFLICT DO UPDATE ... WHERE in_flight_since IS NULL`,
  relative budget increment, and a reserved high-severity band.
- **Prompt-injection delimiter stripping** (`classifier.py:114`,
  `synthesis.py:157`): untrusted text / DB row values containing the
  literal `<<<...END>>>` marker forge the region close. One shared
  `_sanitize()` stripping both markers from every interpolated value —
  folds into the H14 injection-corpus gate in
  `tasks/security/threat-model-remediation.md`.
- **Redaction correctness** (`redact.py`, `executor.py:56-82`): extends
  the already-tracked "redaction covers identifiers/bind values, not just
  SQL literals [H5/M10]" item in `threat-model-remediation.md` — a flagged
  cell should be replaced with a fixed `***` token regardless of shape
  (bare emails/names pass through today), known-sensitive columns should
  default-ON, and `QueryResult.sql` should be redacted or the docstring
  corrected.
- **Oracle/QuestDB runner error wrapping** (`executor.py:167-214`): wrap
  connect/exec exceptions for parity with `PostgresRunner` so raw driver/
  server text does not flow into `QueryResult.error` → LLM/Slack/Jira.
- **Secret-mask completeness** (`logging_setup.py:24`): feed the filter
  the resolved DB/replication credentials at startup, or forbid
  interpolating DSNs/raw exceptions into log records. (Pre-prod applier
  form is tracked as M6 in `threat-model-remediation.md`.)
- **Check_MK input hardening** (`checkmk.py:66,77,114`; `capacity.py:81`):
  `urllib.parse.quote(host)`; guard `float()/int()/json.loads` on a 200-OK
  body; `math.isfinite` guard so a `nan` sample can't abort `synthesize()`.
- **`_FORBIDDEN_KEYWORDS` review** (`playbooks.py:13-16`): it false-rejects
  legit read queries containing e.g. `'DELETE'` in a predicate and misses
  `pg_read_file`/`COPY ... TO PROGRAM`/`dblink`. Rely on grants + human
  YAML review, or replace with a token-parsed single-`SELECT` allowlist.
- **Housekeeping**: `llm_budget`/`fingerprint_state` grow one row per
  day/fingerprint forever (prune or accept); no production caller closes
  the `CooldownStore`/`DiagnosisStore` sqlite connections.

## v1.5

- Live Jira creation (v0/v1 emit a draft only) + @-mention follow-ups
  bounded to the read-only playbook catalogue + feedback (👍/👎) metrics
  dashboarded.

## v2 — write path

- The runbook action catalogue + applier + GitLab merge gate →
  `tasks/apply/runbook-apply-path.md` (blocked on `poc/e2e-demo`).
- All "Pre-prod gates" in `tasks/security/threat-model-remediation.md`
  must be closed before any production wiring — that section is the
  authoritative go-live checklist alongside
  `docs/apply-path-security-model.md` §6.
