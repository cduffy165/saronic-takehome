# App Factory

A platform where business users request internal applications. The factory plans, builds,
reviews, and registers them. Every app gets named owners and attributed cost.

The value is the full lifecycle and the registry, not the quality of generated apps.
Generated apps are deliberately small — this is a POC.

## Status

Through M4: FastAPI orchestration API, Streamlit UI, Postgres registry, Keycloak-backed
identity, and the Plan stage — an interactive session (Claude Agent SDK) that gathers
requirements from a business user and ends in one of three outcomes: `proceed` (fits the
blueprint, Gate 1 approval queues it for Build), `route_to_human` (overlaps an existing app or
exceeds blueprint scope — names a real owner), or `feature_request` (files a change against an
existing app). No Build/Review yet — see the plan for the milestone sequence.

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

## Plan session

`factory/agents/plan_session.py` drives the real Claude Agent SDK, which is a thin Python
wrapper around the actual Node-based `claude` CLI run as a subprocess — the `api` image installs
Node and `@anthropic-ai/claude-code` for exactly this. The SDK is configured for isolation
(`setting_sources=[]`, `strict_mcp_config=True`) so it doesn't inherit a developer's local
`~/.claude` hooks/skills/plugins; without this, a session run from inside a Claude Code dev
environment silently pulls in that entire stack and burns tens of thousands of extra tokens.
**Only ever run or test this SDK from inside a container** (the `api` service, or one built from
`Dockerfile.api`) — never against a host-side Anthropic key, for the same isolation reason.

Requires `ANTHROPIC_API_KEY` in `.env` (real, billed API calls — a few cents per planning turn).
The 8-turn planner cap is enforced by us (`Run.turns_used`), independent of the SDK's own
per-connection `max_turns`, since each HTTP request is a fresh SDK client resuming the session.

## Evals

Tier 2 — costs real money, run deliberately, never as part of `make test`:

```
docker compose up --build   # api + postgres + keycloak must be running
uv run alembic upgrade head
make seed
make eval-routing           # execs into the api container
```

`evals/routing_cases.yaml` holds a small representative set (one per outcome); scaling to more
cases is mechanical. Each case uses a `ScriptedRequester` (`evals/scripted_requester.py`) —
canned answers keyed by keyword — to drive the multi-turn Plan session deterministically.

## Development

```
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```
