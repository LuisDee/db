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

- [ ] Synthesis prompt: verdict-first format, evidence-cited, no speculation beyond evidence
- [ ] Reply renderer (Slack blocks): 2-line verdict + collapsed detail
- [ ] "Nothing to add" suppression path
- [ ] Every diagnosis persisted (alert, evidence, reply, reactions) for the accepted-rate metric
