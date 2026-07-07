# Tasks — DBA agent POC

Work items for the DBA alerts agent, tracked as Structured Tasks:
markdown files with a `depends_on` DAG in frontmatter, checklists as the
only status, commit hashes as merge evidence. See
`docs/dba-agent-direction.md` for the why; see
`project-management/scripts/` for the compliance/branch-guard tooling.

## POC dependency graph

`depends_on` frontmatter is the source of truth; this diagram is kept
in sync with it, not the other way around. `[x]` = done and merged.

```
foundation/agent-skeleton [x]
 ├── foundation/endpoint-registry [x] ──┐
 ├── foundation/compose-stack [x] ──────┼── foundation/integration-test-infra [x]
 │                                      │        └── playbooks/playbook-framework [x]
 │                                      │             ├── playbooks/playbook-disk-space [x]      ─┐
 │                                      │             ├── playbooks/playbook-replication-lag      ─┤
 │                                      │             └── playbooks/playbook-tablespace-usage     ┤
 ├── listener/slack-listener                                                                      │
 └── listener/alert-classifier [x]                                                                │
      ├── triage/dedup-cooldown [x]                                                               │
      ├── triage/diagnosis-synthesis [x] (also needs playbook-framework [x]) ───────────────────┘
      └── digest/noise-digest

poc/e2e-demo ← diagnosis-synthesis [x] + dedup-cooldown [x] + compose-stack [x]
              + playbook-disk-space [x]
     └── apply/runbook-apply-path (v2 write path, blocked on the demo)
```

Note: `listener/slack-listener` is NOT a dependency of anything on the
demo's critical path per its own frontmatter — `poc/e2e-demo` can be
satisfied by the alert-injector (already built in compose-stack)
driving the classifier/executor/synthesis chain directly, without a
live Socket Mode listener. Build `slack-listener` separately if/when a
genuinely live-Slack-driven demo (rather than script-driven) is wanted.

**Every direct dependency of `poc/e2e-demo` is now done.** That's the
only task left to reach the POC's exit criterion — it's pure
integration/wiring work (`make demo`, the cooldown-suppresses-a-repeat
proof, the Oracle tablespace second demo, the stakeholder write-up),
not new component-building.

Everything except `apply/` is POC scope: prove the loop locally in
containers before anything touches a real host. Further post-POC work
(live Jira, coverage advisor, capacity forecasting) gets registered as
new tasks when the POC demo passes.
