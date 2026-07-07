# Threat-model remediation

Findings from the 2026-07-07 adversarial review
(`docs/security-threat-model.md`). Split into POC-era items (bake into
the build now — cheap) and pre-prod gates (block production wiring via
the go-live checklist in `apply-path-security-model.md` §6). Concrete
doc-level fixes (C3 over-grant, H7 compile bug) are already applied to
the security-model doc and spec §6.

## POC-era — build these into the code from the start

- [x] Untrusted-data discipline in every LLM prompt [T2/T4/H10]: all
      alert text and all DB-captured text (query text, object names,
      errors) delimited and labelled as data, never in the instruction
      region; system/policy prompt in a channel the data can't reach.
      (commits: `classifier.py`'s `_ALERT_TEXT_START`/`_ALERT_TEXT_END`
      pattern, tasks/listener/alert-classifier.md; `synthesis.py`'s
      identical `_DATA_START`/`_DATA_END` pattern for evidence-bundle
      content, tasks/triage/diagnosis-synthesis.md — verified during
      the 2026-07-07 retrospective adversarial review, both modules
      independently arrived at the same delimiter discipline)
- [x] Closed-enum classifier/synthesis outputs (`alert_class`,
      `severity` in `classifier.py`; `owner` in `synthesis.py`) — never
      passed through as raw LLM text, always coerced to a known value
      or a safe fallback [H10/LLM-F12] (same commits as above).
- [ ] Host must resolve to a registry key or route to do-nothing;
      ambiguous/low-confidence → refuse, never nearest-match
      [H10/LLM-F12]. **Not done** — this is dispatcher-level wiring
      (classifier's extracted `Classification.host` → `registry.resolve()`
      → handle `UnknownEndpointError` as a first-class "unknown host,
      do nothing" outcome) that doesn't exist yet; no dispatcher has
      been built (tracked in `tasks/poc/e2e-demo.md`). Split out from
      the bullet above during the 2026-07-07 retrospective review,
      which had incorrectly implied both halves were the same item.
- [ ] Alert-source allowlist in the listener [T1/C4]: only allowlisted
      bot/webhook identities are triage-actioned; everything else is
      digest-only.
- [ ] Bind variables for every playbook parameter; reject any playbook
      whose SQL interpolates a parameter [M8].
- [ ] Redaction runs BEFORE the LLM call, and covers identifiers/bind
      values, not just SQL literals [H5/M10].
- [ ] Fingerprint includes a trusted non-LLM field; high-severity is
      never fully silenced (minimal trace always) [H11].
- [ ] Adversarial/injection corpus as a required classifier+synthesis
      test gate (steering, fingerprint collision, second-order DB-text
      injection) — measure "refuses to be steered" [H14].
- [ ] Synthesis never emits copy-pasteable privileged SQL/shell; all
      change recommendations route through the gated action path [H12].
- [ ] Evidence rendered as inert text (no Slack mrkdwn/link injection);
      Check_MK lookups constrained to the provenance-resolved host [M10].

## Pre-prod gates — block production wiring until resolved

- [ ] **GitLab tier decision** [C1]: Premium (Protected Environments +
      approval rules + CODEOWNERS) OR the protected-tag-apply +
      merge-only-main + applier-pins-approved-SHA design. Two gates must
      be real and DBA-restricted; reviewed content == merged content.
- [ ] **Runner isolation** [C2]: dedicated, protected-ref-only, untagged
      off, egress firewalled to the one target host:port; pre-merge
      pipelines routed to a runner with no prod route.
- [ ] Action-file-only diff guard: CI fails any apply pipeline whose
      diff leaves `actions/pending/`; consider splitting the executable
      surface (templates/applier/CI/provisioning) into a
      stricter-controlled project [H1].
- [ ] Environment-scoped `DBA_APPLY_*` variables; each job sees only its
      target's credential [H2].
- [ ] Agent GitLab token = narrowest capability, cannot run manual jobs
      or read protected artifacts; short TTL; not colocated with read
      creds [H3/M7].
- [ ] Every prod-enabled action has a Layer-3 procedure; no
      `scoped-grant` on prod relying on Layer 2 alone [H4/H8].
- [ ] Aggregate/file-count caps in `add_datafile`; forbid `VACUUM
      FULL`/`CLUSTER`; per-table `MAINTAIN`, never the role [H6/H8].
- [ ] In-procedure `lock_timeout` (PG) / profile limits (Oracle) as the
      real bound; role GUCs treated as hygiene only [H9].
- [ ] Append-only audit owned by the definer; engine audit captures the
      DDL not just the EXECUTE [M1/M2].
- [ ] RO credential hardened + network-scoped + rotated; its real reach
      (stats MCVs, live query literals) documented [H5/M3].
- [ ] Allowlist-table contents provisioned from git and audited [M4];
      Oracle owner has no `CREATE SESSION` [M5].
- [ ] Ephemeral executor + digest-pinned image; applier never logs
      DSN/errors; `CI_JOB_TOKEN` allowlist minimal [M6].
- [ ] Secrets split by blast radius; MR-creation behind a separate
      minimally-scoped service; read creds fetched per-query from a
      vault with short TTL [M7].
- [ ] Data-classification decision for Anthropic API egress recorded
      [M10]; per-source LLM budget + MR-rate limits, degrade-to-queue
      not silent-drop [M9]; `gather_stats` marked irreversible +
      target-allowlisted + second-approver class [M9].
- [ ] Second, distinct approver for prod-tier actions; MR foregrounds
      target+params, de-emphasizes non-executed `rendered_sql`; approval
      rate tracked as a fatigue metric [H12].
