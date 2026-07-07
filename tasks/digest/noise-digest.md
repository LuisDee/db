---
depends_on:
  - /tasks/listener/alert-classifier.md
---

# Weekly noise digest

Batch job (weekly): read the alert channel's last 7 days, classify
every message (reuses the alert classifier), and post one summary:
counts by class and host, flap detection (CRITICAL→RECOVERY cycles),
alerts nobody reacted to, and concrete suggestions ("suppress the
nightly refresh Started/Finished pair", "QuestDB check on uk02vddb301
flapped 11 times — needs RCA, not alerting"). Given 63% of current
volume is noise, this is the cheapest high-visibility win in the
project.

## Deliverables

- [ ] Channel history reader (7-day window, pagination)
- [ ] Flap detection over classified sequence
- [ ] Digest renderer: counts, top noise sources, suppression suggestions
- [ ] Schedule hook (cron-style in the agent container)
