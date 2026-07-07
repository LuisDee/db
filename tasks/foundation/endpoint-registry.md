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

- [ ] Registry schema + loader with validation and helpful errors
- [ ] Lookup by exact host, DB name, and alias list
- [ ] Credential refs resolve via env only (no secrets in the YAML)
- [ ] Unit tests incl. unknown-host and ambiguous-alias cases
