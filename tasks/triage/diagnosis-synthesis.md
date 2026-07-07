---
depends_on:
  - /tasks/listener/alert-classifier.md
  - /tasks/playbooks/playbook-framework.md
---

# Diagnosis synthesis

Turn an evidence bundle into the threaded Slack reply: two-line verdict
first, evidence table, suggested action, Jira draft when infra-owned.
Confidence is derived from evidence (do the sources corroborate?), not
from asking the model how sure it is. If the playbook found nothing
beyond what the alert already said, the reply is one line or nothing —
noise discipline is a feature.

## Deliverables

- [x] Synthesis prompt: verdict-first format, evidence-cited, no speculation
      beyond evidence (commit: fee414a — `src/dba_agent/synthesis.py`'s
      `SYSTEM_PROMPT`/`build_synthesis_prompt()`/`parse_diagnosis()`, mirroring
      `classifier.py`'s delimited-untrusted-data + never-raises-on-malformed-
      output pattern exactly (module docstring spells out the mapping). Prompt
      requires per-claim evidence citation and a closed `owner` enum
      (`infra`/`db`/`None`). **Unit-tested** against `FakeLLMClient`
      (`tests/test_synthesis.py`, 22 cases: happy path, malformed/non-object/
      missing-field JSON, out-of-enum owner, non-bool `has_findings`,
      non-string verdict/detail — all coerce to a safe result, never raise).
      **Live-verified for wiring, not for model quality**: real evidence from
      the real filesystem-disk-space playbook against this sandbox's real
      Postgres actually reaches the prompt
      (`tests/integration/test_synthesis_disk_space_wiring.py`, commit:
      60c3578). Actual synthesis *judgement* quality (does a real model
      genuinely cite evidence, suppress correctly, resist injection) is
      **structurally ready but unproven** —
      `tests/integration/test_synthesis_live.py` (commit: 60c3578) is written
      and confirmed to skip cleanly here (no `ANTHROPIC_API_KEY` in this
      sandbox); needs a real key to actually run.
- [x] Reply renderer (Slack blocks): 2-line verdict + collapsed detail
      (commit: fee414a — `render_slack_text()`. Researched Slack's own docs
      first (see module docstring): top-level Block Kit `blocks` are *not*
      auto-collapsed with a "see more" the way `attachments` content is, and
      `SlackClient.post_message` (`src/dba_agent/slack.py`) only accepts plain
      `text` today, so this renders a single well-ordered `mrkdwn` string —
      verdict bold and first, detail after, Jira draft appended when present
      — rather than inventing a Block Kit structure the transport can't send.
      `slack.py` was **not modified** — no extension needed. Unit-tested:
      verdict-first ordering, detail omitted when blank, Jira draft section
      included when attached. **Follow-up from the 2026-07-07
      retrospective adversarial review**: the original version embedded
      verdict/detail/Jira-draft text with no escaping — a threat-model
      M10 gap (crafted DB evidence or LLM output containing
      `<http://evil|click>`-shaped text would have rendered as a live
      Slack link). Fixed: `_escape_mrkdwn()` now escapes `&`/`<`/`>` per
      Slack's own entity-escaping rule, applied to every field that
      traces back to untrusted content, with a test proving injection-
      shaped text renders inert.
- [x] "Nothing to add" suppression path (commit: fee414a — `has_findings` on
      `Diagnosis` is the signal (coerced `False` on any malformed/empty/non-
      bool response, and correctly `False`/`True` from a well-formed
      scripted "nothing new here" vs. genuine-finding response); `should_post()`
      names the check for a future caller — no listener/dispatcher exists yet
      to actually wire the suppression into (that's a separate, not-yet-built
      task), so this is tested as a pure decision function, not an end-to-end
      no-post proof. Live-verified in the wiring integration test too: a
      scripted "nothing beyond what the alert already said" response yields
      `should_post() is False` against a real evidence bundle (commit: 60c3578).
- [x] Every diagnosis persisted (alert, evidence, reply, reactions) for the
      accepted-rate metric (commit: b836d03 —
      `src/dba_agent/diagnosis_store.py`'s `DiagnosisStore`, stdlib `sqlite3`,
      its own schema/file, `db_path` an explicit constructor argument (never
      hardcoded) so tests use `tmp_path`. Deliberately not sharing storage
      with the sibling `dedup-cooldown` task's own SQLite state. `reactions`
      starts `NULL`; `update_reactions()` exists and is tested with a hand-set
      value — no Slack reaction listener exists yet to call it for real.
      Unit-tested (`tests/test_diagnosis_store.py`, 7 cases: round-trip,
      unknown id, null reactions, update-then-read, distinct ids, reopen
      across connections, failed-query evidence serializes without raising).
      Live-verified end-to-end too: a real evidence bundle from the real
      Postgres playbook round-trips through `record()`/`get()`
      (`tests/integration/test_synthesis_disk_space_wiring.py`, commit:
      60c3578).

## Retrospective addendum (2026-07-07 adversarial review)

An adversarial cross-task review (run after this task and
`tasks/playbooks/playbook-disk-space.md` were both already marked
complete) found that `checkmk.py`/`capacity.py` — built for the
disk-space playbook — were never actually called from
`synthesize()`, despite both tasks' checkboxes implying an end-to-end
time-to-full estimate. Fixed here: `synthesize()` gained an optional
`checkmk_client: CheckMkClient | None = None` + `checkmk_history_hours`
parameter (default `None` preserves the exact original behaviour for
every pre-existing caller/test); when a caller supplies one along with
a classification that has a host + subject, `_try_estimate_time_to_full`
genuinely calls `filesystem_history()` → `estimate_time_to_full()` and
threads the result into the Jira draft, degrading safely to the
original "not available" section on any failure. New tests prove the
threading, the unmodified-default behaviour, and the failure-tolerance
path. See `tasks/playbooks/playbook-disk-space.md`'s matching addendum.
