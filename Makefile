# Local proof environment for the DBA agent -- see compose/README.md for
# the full layout and RAM budget, and tasks/foundation/compose-stack.md
# for what this proves. "make up" starts the whole stack; nothing here
# touches a real host, credential, or Slack channel.

COMPOSE_FILE := compose/compose.yaml
COMPOSE_ENV  := compose/.env
COMPOSE      := docker compose --env-file $(COMPOSE_ENV) -f $(COMPOSE_FILE)

# TYPE selects which alert fixture(s) to inject (see
# compose/injector/fixtures/alerts.json), or 'all'. SLACK_MODE=fake
# (default) needs no credentials; SLACK_MODE=real needs SLACK_BOT_TOKEN
# + SLACK_TEST_CHANNEL in compose/.env.
TYPE ?=
SLACK_MODE ?= fake

.PHONY: up down clean ps logs seed inject-alert help

help:
	@echo "make up            -- build + start the full stack, wait for all healthy"
	@echo "make down          -- stop the stack (keeps volumes/data)"
	@echo "make clean         -- stop the stack AND delete all volumes (fresh start next 'make up')"
	@echo "make ps            -- show service status"
	@echo "make logs          -- follow all service logs"
	@echo "make seed          -- idempotent re-seed of postgres, oracle, and questdb"
	@echo "make inject-alert TYPE=disk-space   -- inject one alert-fixture class (see compose/injector/fixtures/alerts.json)"
	@echo "make inject-alert TYPE=all          -- inject the whole ~10-message corpus"

up: $(COMPOSE_ENV)
	$(COMPOSE) up -d --build --wait

down: $(COMPOSE_ENV)
	$(COMPOSE) down

clean: $(COMPOSE_ENV)
	$(COMPOSE) down -v

ps: $(COMPOSE_ENV)
	$(COMPOSE) ps

logs: $(COMPOSE_ENV)
	$(COMPOSE) logs -f

$(COMPOSE_ENV):
	$(error compose/.env is missing -- copy compose/.env.example to compose/.env first (dev-only placeholder values, see that file's comments))

# Re-runs the same SQL files the first-boot init hooks use, against the
# already-running containers. All three engines' seed scripts are
# written to be idempotent (see comments in each file), so this is safe
# to run repeatedly -- e.g. after `make inject-alert` if you want to
# confirm the databases are still queryable, or after a manual data
# tweak you want to reset.
seed: $(COMPOSE_ENV)
	@echo "== postgres =="
	@for f in compose/postgres/init/01_replication_role.sql \
	          compose/postgres/init/02_extensions.sql \
	          compose/postgres/init/03_schema_seed.sql; do \
		echo "-- $$f"; \
		$(COMPOSE) exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 < $$f || exit 1; \
	done
	@echo "== oracle =="
	@ORACLE_PW=$$(grep -E '^ORACLE_PASSWORD=' $(COMPOSE_ENV) | cut -d= -f2-); \
	for f in compose/oracle/init/01_tablespace_and_user.sql \
	         compose/oracle/init/02_fill_tablespace.sql; do \
		echo "-- $$f"; \
		$(COMPOSE) exec -T oracle sqlplus -s "sys/$${ORACLE_PW}@localhost/FREEPDB1 as sysdba" < $$f || exit 1; \
	done
	@echo "== questdb =="
	python3 compose/questdb/seed.py

inject-alert: $(COMPOSE_ENV)
	@if [ -z "$(TYPE)" ]; then \
		echo "usage: make inject-alert TYPE=<slug> (see compose/injector/fixtures/alerts.json), or TYPE=all"; \
		exit 1; \
	fi
	$(COMPOSE) run --rm --no-deps \
		-v $(CURDIR)/compose/injector:/injector \
		agent python /injector/inject.py --type $(TYPE) --slack-mode $(SLACK_MODE)
