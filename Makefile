.PHONY: seed migrate lint test eval

seed:
	uv run python -m factory.registry.seed

migrate:
	uv run alembic upgrade head

lint:
	uv run ruff format .
	uv run ruff check .

test:
	uv run pytest

# Tier 2 targets land with their respective milestones (M4+); each will call a
# model and cost money, so they are not part of `make test`. Run inside the api
# container (not on the host) — that's where the isolated, container-only
# claude-agent-sdk setup lives.
eval-routing:
	docker compose exec api uv run python -m evals.run_routing_eval

eval-hostile:
	@echo "eval-hostile: not yet implemented (M4)"

eval-review:
	docker compose exec api uv run python -m evals.run_review_eval

eval-build:
	docker compose exec api uv run python -m evals.run_build_eval

eval: eval-routing eval-hostile eval-review eval-build
