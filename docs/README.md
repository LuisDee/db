# docs

Design history for the DBA agent, in chronological order:

- `dba-alerts-bot-spec.md` — the original spec (draft v0.1),
  **superseded**, kept for history.
- `dba-alerts-bot-spec-review.md` — adversarial review of v0.1, with a
  sourced research verification pass.
- `dba-agent-direction.md` — the decision log (why v0.2 differs from
  v0.1).
- `dba-agent-spec.md` — **spec v0.2, canonical. Start here.** Work
  items live in `tasks/`.
- `apply-path-security-model.md` — the write-path security model:
  template-only execution, the four containment layers, worked
  Oracle/Postgres least-privilege examples, and the **production
  go-live checklist**. Required reading before wiring anything into a
  real database.
- `security-threat-model.md` — consolidated adversarial review (CI/
  credential, DB privilege, LLM/prompt-injection). Trust boundaries,
  ranked findings, and the **phase-by-phase readiness verdict**. Read
  before building the read path or the applier. Remediation is tracked
  in `tasks/security/threat-model-remediation.md`.
