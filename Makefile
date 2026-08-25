.PHONY: up seed migrate lint test eval gitea-init

# One-command bring-up: builds and starts every service, mints and stores a
# Gitea token, runs migrations, and loads the registry seed. Docker is the
# only requirement — see scripts/bootstrap.sh for what it does.
up:
	./scripts/bootstrap.sh

seed:
	uv run python -m factory.registry.seed

migrate:
	uv run alembic upgrade head

# One-time setup: creates the "factory" service account Gitea repos are pushed
# under, and prints an access token to paste into .env as GITEA_TOKEN. Safe to
# re-run — user creation is idempotent-ish (Gitea errors harmlessly if it
# already exists); re-running just mints a fresh token.
gitea-init:
	docker compose exec --user git gitea gitea admin user create \
		--username factory --password "$${GITEA_PASSWORD:-factory-dev-password}" \
		--email factory@localhost --admin --must-change-password=false || true
	docker compose exec --user git gitea gitea admin user generate-access-token \
		--username factory --token-name factory-api-$$(date +%s) \
		--scopes write:repository,write:user

lint:
	uv run ruff format .
	uv run ruff check .

test:
	uv run pytest

# Each of these calls a real model and costs money, so they are not part of
# `make test`. Run inside the api container (not on the host) — that's where
# the isolated, container-only claude-agent-sdk setup lives.
eval-routing:
	docker compose exec api uv run python -m evals.run_routing_eval

eval-hostile:
	@echo "eval-hostile: not yet implemented"

eval-review:
	docker compose exec api uv run python -m evals.run_review_eval

eval-build:
	docker compose exec api uv run python -m evals.run_build_eval

eval: eval-routing eval-hostile eval-review eval-build
