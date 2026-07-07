---
depends_on:
  - /tasks/triage/diagnosis-synthesis.md
  - /tasks/triage/dedup-cooldown.md
  - /tasks/foundation/compose-stack.md
  - /tasks/playbooks/playbook-disk-space.md
---

# POC end-to-end demo

The exit criterion for the whole POC, run entirely in the local compose
stack: `make inject-alert TYPE=disk-space` posts a real (recorded)
Check_MK filesystem alert → listener picks it up → classifier extracts
host → registry resolves the compose QuestDB/Postgres endpoint →
disk-space playbook gathers evidence → synthesized diagnosis lands as a
threaded reply (fake or test-workspace Slack) with a Jira draft →
injecting the same alert again within the cooldown produces no second
diagnosis. Recorded as a short demo script/GIF for the stakeholders.

This proves the loop with zero connection to real infrastructure —
the agreed bar before any real host, credential, or channel is touched.

## Deliverables

- [ ] One-command demo: `make demo` from cold start
- [ ] Duplicate-injection shows cooldown working
- [ ] Tablespace scenario as second demo (oracle-free)
- [ ] Demo write-up in docs/ with screenshots for the AI-integration stakeholders
