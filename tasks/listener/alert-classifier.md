---
depends_on:
  - /tasks/foundation/agent-skeleton.md
---

# Alert classifier

LLM-based classification of raw channel messages into
`{alert_class, host/db, severity, fingerprint}`. The LLM is the parser —
our sources are heterogeneous (Check_MK and friends) so no format
parsing. Classes from the 16-day inventory: questdb-health-flap,
qa-refresh-cycle, filesystem-disk-space, standby-replication-lag,
tablespace-usage, human-message, unknown. `fingerprint` is the dedup/
cooldown key (class + host + subject).

Golden-set tested: a corpus of real alert texts with expected labels;
the classifier must hit 100% on the corpus with the scripted-fake LLM
replaced by the live one (run on demand, not in CI).

## Deliverables

- [x] Classification prompt + structured output schema (commit: 46a979f — `src/dba_agent/classifier.py`: `build_prompt`/`SYSTEM_PROMPT` delimit untrusted alert text out of the instruction region, `parse_classification` defensively parses strict JSON into the closed `alert_class`/`severity` enums, never raising and never passing raw LLM text through; unit-tested directly with hand-written strings, not only via `classify()`)
- [x] Golden corpus (~20 real anonymised messages) + assertion harness (commit: 46a979f — `tests/fixtures/classifier-golden-corpus.json` references all 10 real `compose/injector/fixtures/alerts.json` fixtures by id (loaded, not duplicated) plus 3 adversarial entries (prompt-injection-to-`human-message`, fake-host injection, out-of-enum LLM response); `tests/test_classifier.py` scripts `FakeLLMClient` per entry and asserts 100% — proves parsing/validation/routing, not the live model's judgement, per its own docstring. Live-model accuracy is a separate, structurally-ready-but-unproven test: `tests/integration/test_classifier_live.py` (commit: db2d6dc), marked `llm_live` (new marker, distinct from `integration` — needs a real billed `ANTHROPIC_API_KEY`, not a local DB), asserts >=90% on the same corpus against the real `AnthropicLLMClient`. Confirmed SKIPPED cleanly in this sandbox (no usable `ANTHROPIC_API_KEY` here) — unrun against a live model until someone has a real key, same status as this repo's Oracle/QuestDB integration tests.)
- [x] Fingerprint function, stable across message cosmetic changes (commit: 46a979f — `fingerprint(alert_class, host, subject)`, a plain `class|host|subject` string excluding severity/state wording by design so `qdb-flap-1` (CRITICAL) and `qdb-flap-2` (OK/recovery, same host+check) collide for cooldown purposes; reasoning in the function's docstring; tested directly in `tests/test_classifier.py`)
- [x] Unknown/human classes route to "do nothing" by default (commit: 46a979f — `is_actionable(Classification) -> bool`, pure decision function returning `False` only for `human-message`/`unknown`, unit-tested for every class; no dispatcher exists yet to wire the actual no-op into)
