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

- [x] Package layout (`src/dba_agent/`), pyproject, pytest + ruff green in CI (commit: a755b81)
- [x] Config loading (env + YAML), secrets only via env, never logged (commit: a755b81)
- [x] LLM client wrapper (Anthropic API) + scripted fake for tests (commit: c7dda52)
- [x] Slack client wrapper + in-memory fake (records posts for assertions) (commit: c7dda52)
- [x] Dockerfile; container starts, healthcheck endpoint answers (commit: 561c8b6 — verified without a Docker daemon, unavailable in this sandbox: exact `pip install .` in an isolated venv, then `python -m dba_agent.app` run as its own subprocess, healthcheck answered 200, SIGTERM clean-exit 0. Building/running the actual image is a follow-up smoke test the first time a real Docker host is available.)
- [x] Structured logging with secret masking (commit: a755b81)
