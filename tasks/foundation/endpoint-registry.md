---
depends_on:
  - /tasks/foundation/agent-skeleton.md
---

# Endpoint registry

Maps a hostname or DB name extracted from an alert (`uk01vdb301`,
`boproddb`, `dev`) to a connectable endpoint: engine (postgres | oracle
| questdb), DSN, read-only credential reference, and environment tag.
YAML file in-repo for the POC (mirrors the `oracdb` endpoints-registry
pattern). Lookup failures are a first-class outcome — the triage reply
says "unknown host" rather than guessing.

## Deliverables

- [x] Registry schema + loader with validation and helpful errors (commit: b1bc365)
- [x] Lookup by exact host, DB name, and alias list (commit: 42f091c)
- [x] Credential refs resolve via env only (no secrets in the YAML) (commit: ed74049)
- [x] Unit tests incl. unknown-host and ambiguous-alias cases (commit: caca6e8)
