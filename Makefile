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
# model and cost money, so they are not part of `make test`.
eval-routing:
	@echo "eval-routing: not yet implemented (M4)"

eval-hostile:
	@echo "eval-hostile: not yet implemented (M4)"

eval-review:
	@echo "eval-review: not yet implemented (M5)"

eval-build:
	@echo "eval-build: not yet implemented (M5)"

eval: eval-routing eval-hostile eval-review eval-build
