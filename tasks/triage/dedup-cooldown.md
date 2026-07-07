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

- [ ] Fingerprint cooldown window (configurable per class)
- [ ] Repeat handling: silent or thread-counter update, never a new diagnosis
- [ ] Persistent in-flight marker; crash/restart test
- [ ] Per-day LLM call budget with loud logging when hit
