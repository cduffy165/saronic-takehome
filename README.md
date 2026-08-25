# App Factory

A platform where business users request internal applications. The factory plans, builds,
reviews, and registers them. Every app gets named owners and attributed cost.

The value is the full lifecycle and the registry, not the quality of generated apps.
Generated apps are deliberately small — this is a POC.

## Status

Skeleton stack only (M1): FastAPI orchestration API, Streamlit UI, Postgres. No planning,
building, review, or registry logic yet — see the plan for the milestone sequence.

## Running

```
docker compose up --build
```

- API: http://localhost:8000/health
- UI: http://localhost:8501

## Development

```
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```
