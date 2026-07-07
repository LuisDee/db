# Agent skeleton

Standalone Python app (this repo), containerized. Establishes the
package layout, config loading, and the seams everything else plugs
into: an LLM client wrapper, a Slack client wrapper with an in-memory
fake, and test/lint plumbing. No business logic yet — this is the
walking skeleton the other tasks hang off.

Decisions baked in (see `docs/dba-agent-direction.md`): Python;
constructor-injected dependencies with plain fakes (no ports/adapters
framework); the agent core never holds write credentials.

## Deliverables

- [ ] Package layout (`src/dba_agent/`), pyproject, pytest + ruff green in CI
- [ ] Config loading (env + YAML), secrets only via env, never logged
- [ ] LLM client wrapper (Anthropic API) + scripted fake for tests
- [ ] Slack client wrapper + in-memory fake (records posts for assertions)
- [ ] Dockerfile; container starts, healthcheck endpoint answers
- [ ] Structured logging with secret masking
