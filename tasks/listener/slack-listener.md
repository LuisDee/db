---
depends_on:
  - /tasks/foundation/agent-skeleton.md
---

# Slack listener

Bolt (Socket Mode) listener on the alerts channel. Socket Mode = no
public ingress needed. Ack immediately, enqueue, process async; dedup
on Slack `event_id` (Slack retries 3x on slow ack and never dedups for
you). Must handle `bot_message` subtypes since alerts are posted by
other bots/webhooks. Threading rule: reply with `thread_ts` = parent
message `ts`.

## Deliverables

- [ ] Socket Mode listener wired to the Slack wrapper (fake-testable)
- [ ] Immediate ack + async processing queue
- [ ] Dedup on event_id with persistence across restart
- [ ] Captures bot/webhook-authored messages, ignores own posts
- [ ] 👍/👎 reaction capture on the agent's replies, persisted
