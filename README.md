# App Factory

A platform where business users request internal applications. The factory plans, builds,
reviews, and registers them. Every app gets named owners and attributed cost.

The value is the full lifecycle and the registry, not the quality of generated apps.
Generated apps are deliberately small — this is a POC.

## Status

Through M3: FastAPI orchestration API, Streamlit UI, Postgres registry (models, migrations,
idempotent seed loader, read-only browser), and Keycloak-backed identity. No planning,
building, or review logic yet — see the plan for the milestone sequence.

## Running

```
cp .env.example .env
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # dev-only values, see below
docker compose up --build
uv run alembic upgrade head
make seed
```

- API: http://localhost:8000/health
- UI: http://localhost:8501 (log in as `alice`/`alice`, `bob`/`bob`, `carol`/`carol`, or
  `dave`/`dave` — see `keycloak/realm-export.json`)
- Keycloak admin console: http://auth.localhost:8080 (`admin`/`admin`)

If your browser doesn't resolve `auth.localhost` to `127.0.0.1` automatically (most do, per
the `.localhost` TLD convention), add `127.0.0.1 auth.localhost` to your hosts file.

## Identity

Keycloak runs as a container with a small dev-only realm (`keycloak/realm-export.json`,
fixture users only — passwords match usernames). Streamlit's native OIDC (`st.login`) is the
identity provider; `app_owners.keycloak_sub` stores the real OIDC `sub` claim, not a mock
selector.

**Issuer hostname.** Keycloak is configured with `KC_HOSTNAME=auth.localhost` so the browser
and the `ui` container see the identical issuer (`http://auth.localhost:8080/realms/factory`).
Without this, the browser would reach Keycloak at `localhost:8080` while the `ui` container
reached it at `keycloak:8080`, and OIDC discovery/issuer validation would fail on the mismatch.
The `ui` container resolves `auth.localhost` to the host machine via Docker's `host-gateway`
(`extra_hosts` in `compose.yaml`), landing back on Keycloak's published port.

**Trust boundary.** `st.user` exposes the identity token's *claims*, not a verifiable access
token. Any future forwarding from the UI to the API is therefore forwarded claims that the API
trusts, not a token the API independently verifies — acceptable for this POC, not for
production.

## Development

```
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```
