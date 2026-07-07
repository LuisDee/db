# project-management

Structured Tasks tooling. No external task board: work items live in
`tasks/**/*.md` with a `depends_on` DAG, checklists are the only status,
git is the audit trail.

Scripts (`scripts/`):

- `collect-structure-docs/collect-structure-docs.sh` — prints every
  subfolder README with its location. Run first in a new agent session.
- `check-task-compliance/check-task-compliance.sh` — validates task
  filenames (kebab-case, no numeric/TD-XXXX names) and frontmatter
  (only `depends_on`, paths must exist). Run after any task file change.
- `check-branch-name/check-branch-name.sh` — verifies the current git
  branch binds to a task slug (`feat/<slug>`, `TD-XXXX/<slug>`, or bare
  `<slug>` with `tasks/**/<slug>.md` on disk). Run before coding.

Known exception: hosted agent sessions run on harness-assigned
`claude/...` branches, which the branch guard rejects by design. The
guard applies to human/feature branches; agent-session branches document
their task binding in the commit body instead.
