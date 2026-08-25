# App Factory

A platform where business users request internal applications. The factory plans, builds,
reviews, and registers them. Every app gets named owners and attributed cost.

The value is the full lifecycle and the registry, not the quality of generated apps.
Generated apps are deliberately small — this is a POC.

## Status

Through M5: FastAPI orchestration API, Streamlit UI, Postgres registry, Keycloak-backed
identity, the Plan stage (interactive session ending in `proceed` / `route_to_human` /
`feature_request`), and Build + Review. Approving a `proceed` plan (Gate 1) now actually builds
it: a Build session writes a small Streamlit app, a deterministic gate (required files +
gitleaks) runs before Review ever sees it, a Review session grades security/quality, one retry
on failure, then — only after a pass — a real `git commit` and a running Docker container on an
allocated port. No Register yet (App rows aren't created until Gate 2 approval lands) — see the
plan for the milestone sequence.

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

## Build + Review

`factory/agents/build_session.py` writes files only — no Bash, no network, and every Write/Edit
call is checked by a `can_use_tool` path-containment guard (resolved-path containment, rejects
`..`/absolute escapes) so the agent cannot touch anything outside its own `generated_apps/<slug>`
directory. Bringing the container up is deterministic code
(`factory/agents/container_runtime.py`, via `docker-py`), never agent-driven — the `api` service
mounts the host's Docker socket and `./generated_apps` (a bind mount, not a named volume, so the
repo is real files on the host, not trapped in a container).

Order matters and is enforced in code, not convention: Build writes → required-files check +
secrets scan (gitleaks, plus a bespoke check for the literal value of the factory's own
`ANTHROPIC_API_KEY` — gitleaks has no rule for that shape) → Review → only on a pass does
anything get `git commit`ed or run as a container. One retry (2 attempts total) before a run is
marked failed with the accumulated findings.

The `api` container runs as root (needed for Docker socket access), so generated files are
chowned back to `HOST_UID`/`HOST_GID` (default `1000`/`1000`) once each attempt's outcome is
known — override in `.env` if your host user's `id -u`/`id -g` differ. The chown has to happen
*after* `git init`/`commit`, not before: git itself runs as root, and refuses to operate on a
repo it doesn't own (observed live) if the directory is chowned to the host user first.

## Evals

Tier 2 — costs real money, run deliberately, never as part of `make test`:

```
docker compose up --build   # api + postgres + keycloak must be running
uv run alembic upgrade head
make seed
make eval-routing           # 3 cases, one per Plan outcome
make eval-review            # 2 fixtures: a hardcoded secret, an injection risk
make eval-build             # one golden plan through the full pipeline, ~1-2 min
```

All three exec into the `api` container. `evals/routing_cases.yaml` holds a small
representative set (one per outcome); scaling to more cases is mechanical. Each case uses a
`ScriptedRequester` (`evals/scripted_requester.py`) — canned answers keyed by keyword — to drive
the multi-turn Plan session deterministically.

`evals/run_review_eval.py` feeds `evals/review_fixtures/*` straight to the secrets gate and
Review, without going through Build — cheap and isolates what's being tested. `evals/run_build_eval.py`
runs the real pipeline end to end (Build → gate → Review → git commit → Docker). It always
removes its own `Run` database rows so eval runs don't pollute the registry; on success it also
removes the container, image, and generated directory — on failure it leaves the generated
directory in place so you can see what Build actually wrote.

## Development

```
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```

Requires [`gitleaks`](https://github.com/gitleaks/gitleaks) on `PATH` (a single static binary,
no install beyond downloading it) — `factory/agents/secrets_scanner.py`'s tests call the real
binary rather than mocking it, matching the pinned version installed in `Dockerfile.api`:

```
curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz \
  | tar -xz -C ~/.local/bin gitleaks   # or any directory already on PATH
```
