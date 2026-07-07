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

- [ ] Classification prompt + structured output schema
- [ ] Golden corpus (~20 real anonymised messages) + assertion harness
- [ ] Fingerprint function, stable across message cosmetic changes
- [ ] Unknown/human classes route to "do nothing" by default
