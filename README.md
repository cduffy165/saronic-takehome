# App Factory

A platform where business users request internal applications. The factory plans, builds,
reviews, and registers them. Every app gets named owners and attributed cost.

The value is the full lifecycle and the registry, not the quality of generated apps.
Generated apps are deliberately small — this is a POC.

## Status

Through M7. FastAPI orchestration API, Streamlit UI, Postgres registry, Keycloak-backed
identity, the Plan stage (interactive session ending in `proceed` / `route_to_human` /
`feature_request`), Build + Review (Gate 1 approval builds a small Streamlit app, gated by
required-files + gitleaks before Review, then `git commit` and a running Docker container only
after a pass), Register (Gate 2 approval — plain code, no LLM — creates the `App` row, its
owner, its capabilities, and backfills accumulated cost onto it), and feature-request pickup: an
app owner can pick up a request filed against their app, running Plan pre-seeded with the
request, then Build/Review modifying the *existing* repo instead of a fresh one, then Gate 2
appending the new capability instead of creating a new app. See the plan for the milestone
sequence (M8 — seed capture — is next).

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

**API authentication.** `factory/api/auth.py` verifies a real Keycloak-issued bearer token on
every `/plans*` request — signature checked against Keycloak's JWKS, issuer and client (`azp`)
checked against expected values — and derives the caller's identity from the verified `sub`
claim. The API never trusts a client-supplied identity field. Each endpoint also enforces that a
plan run's `requester_sub` matches the verified caller before allowing continuation, reads, or
approval (403 otherwise). The UI exposes the access token via `expose_tokens = ["access"]` in
`secrets.toml` and forwards it as `Authorization: Bearer <token>` on every API call; evals
authenticate the same way, via `evals/keycloak_auth.py` fetching a real token per fixture user
rather than bypassing the check.

An earlier version of this README described unauthenticated forwarding of `st.user`'s claims as
an "acceptable POC trust boundary" — that was an unreviewed unilateral call, not a checked
decision, and a security review later flagged the resulting endpoints as exploitable (any
network peer reaching the API's port could impersonate any user and trigger real Docker builds
on the host). It's fixed now; the API's port is still published on all interfaces rather than
loopback-only like `postgres`, which remains a narrower, separate gap worth closing before any
non-local deployment.

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

**Network isolation.** Generated app code is LLM-authored from a business user's request, and
the only gates before it runs are a static secrets scan and a tool-less LLM review — neither
evaluates runtime network behavior. A security review flagged that generated containers were
originally placed on the same Docker network as `postgres` and `keycloak`, reachable by DNS name
with default dev credentials — a code-execution path with a real lateral-movement route into the
factory's own data store. Generated containers now run on a separate network
(`factory-generated-net`) with no route to `postgres`/`keycloak`; only `api` bridges both
networks, which is what lets it still reach a generated container by internal IP for health
checks. Verified live: a generated container cannot resolve `postgres` by DNS name at all.

## Register

Gate 2 (`POST /builds/{id}/approve`, same ownership check as Gate 1) is the only place an `App`
row gets created — `factory/registry/register.py` is plain code, not agent-driven. It creates
the app, an `AppOwner` (the original requester, as the `business` owner — the plan schema has no
separate "owner" field, so the requester is the natural default), a `Capability` row per declared
capability, and backfills `app_id` onto the plan run, the build/review run, and their existing
`CostEvent` rows — which is what makes "cost accumulated across runs" on the registry page
reflect the real per-stage spend instead of nothing. `factory/registry/slug.py` holds `slugify`
so Build's directory name and the registered `App.slug` always agree.

## Feature request pickup

An app owner sees open requests against apps they own at `GET /feature-requests` (the "Feature
Requests" view in the UI). Picking one up (`POST /feature-requests/{id}/pickup`) starts a normal
Plan session seeded with the request's description, but with `Run.app_id` set to the target app
at creation — the only signal needed: a `proceed` outcome on a plan run whose `app_id` was
already set (not resolved by the outcome itself) means "modify this existing app," not "build a
new one." The same signal branches Build (writes into the existing `repo_path` instead of a
fresh directory; retries discard a failed attempt via `git checkout`/`clean`, never `rm -rf`,
since that would destroy the app being modified) and Register (`register_feature` appends
capabilities and resolves the `FeatureRequest` instead of creating a new `App`).

Two real bugs here, both found by running the actual two-user walkthrough, not by review:
- The existing app's directory is host-owned from its prior registration, but git runs as root
  throughout Build/Review — the same dubious-ownership wall M5 hit on `git init`, except this
  time hit immediately rather than only at commit time, since a pickup's directory doesn't start
  root-owned via `mkdir` the way a fresh build's does. Fixed by chowning back to root for the
  duration of a pickup run, host-owned again only at its return points.
- The per-attempt "chown to host for inspectability" on a failed attempt is safe for a fresh
  build (the next attempt's `rm -rf` + `mkdir` resets ownership regardless) but re-triggers the
  same wall on a pickup retry, since `git checkout`/`clean` operates on that same, now
  host-owned, directory. Pickup skips those per-attempt chowns and only hands ownership back at
  a return point.

Known gap, not yet fixed: if `run_build_and_review` fails *after* `approve_plan` has already
committed (as happened live while chasing the bug above), the plan is left "approved but never
built" with no route back through the API — `plan_approved_at` blocks a retry of the same
endpoint. Needs either an idempotent approve or an explicit re-run path.

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
