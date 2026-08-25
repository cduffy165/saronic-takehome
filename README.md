# App Factory

## What this is

A platform where a business user describes an internal app in plain language, and the factory
plans it, builds it, reviews it, and registers it — with a named owner and an attributed cost —
without an engineer writing a line of code. The user talks to an interactive planner; a human
approves the plan before anything is built and approves the finished artifact before it's
registered; the result is a small, running application and a permanent, queryable record of what
exists, what it does, what it cost, and who's responsible for it.

The value being demonstrated is the **lifecycle and the registry**, not the sophistication of the
generated apps. Generated apps are deliberately small (one architectural pattern: a Streamlit
app on Docker) — the interesting engineering is in the pipeline that plans, builds, reviews,
gates, and accounts for them safely and repeatably.

## Why an enterprise wants this

Every organization above a certain size accumulates small internal tools nobody can account for:
a spreadsheet-replacement app a manager had a contractor build two years ago, a script someone in
ops still runs, an app whose original author left the company. Nobody can answer "what does this
cost us," "who owns it," or "does something like this already exist" — so the same small app gets
rebuilt by three different teams, and nobody can retire anything with confidence because nobody
knows what depends on it.

This platform makes those questions answerable by construction, not by later audit:

- **Every app has a named owner** from the moment it's requested — a real, verified identity
  (Keycloak), not a mailing list or a departed employee's account.
- **Every app's cost is attributed** at the stage level (planning, building, reviewing) from the
  moment it's built, not estimated after the fact.
- **Duplicate requests get routed to the person who already owns the answer**, instead of
  spawning a fourth copy of the same small tool.
- **Changes to an existing app go through its owner**, so capability creep and cost accumulate
  against the same accountable record instead of silently forking.
- **Scope is bounded by policy, not by hope** — a blueprint's complexity ceiling stops a single
  request from one-shotting something that should require an actual architecture conversation.

None of this requires the generated apps themselves to be impressive. The registry is the
product; the apps are proof the registry's data is real.

## Architecture

```
Plan (interactive session)                    Build + Review (one orchestrator, two subagents)
  └─ proceed / route_to_human / feature_request  └─ write files → gate → review → retry (×1)
       │ [HUMAN GATE 1: approve, before spend]         │ [HUMAN GATE 2: approve, before registration]
       ▼                                                ▼
  Register (plain code, no LLM) — creates the App row, owner, capabilities; backfills cost
```

Compose stack: **Postgres** (registry), **Keycloak** (identity), **Gitea** (durable git hosting
for generated apps), **api** (FastAPI orchestration), **ui** (Streamlit). Generated app
containers run as siblings on a separate Docker network, built and started by plain code (never
by an LLM) against the host's Docker socket.

### How it was made reliable

Reliability here didn't come from writing more careful prompts. It came from refusing to let the
model be the only thing standing between a request and an action with real consequences —
every point below is a place where non-determinism was pushed out to code, or where a human was
put in the loop before something expensive or irreversible happened.

**Determinism before judgment.** Whenever a check can be a deterministic function instead of a
model's opinion, it is, and it runs *before* the model gets a vote:
- Build's file writes are checked by a `can_use_tool` path-containment guard — resolved-path
  containment, not a prompt asking the model not to escape its directory.
- Every generated app is scanned by gitleaks (a maintained secrets-pattern library) plus a
  bespoke check for the literal value of the factory's own live API key, and by bandit + ruff's
  security ruleset (`S` rules) for Python-specific antipatterns — all *before* the LLM Reviewer
  ever reads the file tree. A high-severity finding from any of these blocks the pipeline outright;
  the LLM's own judgment only runs on a tree that's already passed the parts that don't need
  judgment at all.
- The planner is never trusted to correctly self-report duplication via a tool call it might get
  wrong — it's handed a full registry digest (real app names, capabilities, owners) as ground
  truth text and told explicitly that a tool's "no match" doesn't mean "no overlap."
- Free-text identifiers the model is asked to echo back are exactly where it hallucinates: it
  once invented a blueprint id that doesn't exist, and separately named a real user by their
  plain username instead of a value that had ever been true. Both are now either supplied by code
  (`blueprint_id` is set by the orchestrator, never solicited) or validated server-side against
  what's actually true (`owner_sub` must be a real, UUID-shaped Keycloak subject who actually owns
  the app in question, or it's substituted with one).

**Two human gates, not one.** Approving the *plan* (before any spend) and approving the *built
artifact* (before it's permanently registered) are different decisions with different stakes, and
collapsing them would mean a human either can't stop a bad plan before it costs money, or can't
stop a working-but-undesirable build from being permanently recorded.

**Bounded retries, bounded turns, bounded scope.** The planner gets 8 turns before it must stop
(never proceeding silently past the cap); Build/Review gets one retry (2 attempts) before it
reports a legible failure instead of looping; a blueprint's numeric complexity ceiling means a
request that's too large routes to a human instead of getting built anyway.

**Isolation as a load-bearing property, not a nice-to-have.** Generated containers run on a
network with no route to Postgres or Keycloak — verified live, not just configured, by an eval
that attempts the connection from inside a real generated container and asserts it fails. The
Claude Agent SDK itself runs with `setting_sources=[]` and `strict_mcp_config=True` so it never
inherits a developer's own tool/skill/plugin stack (an early bug let it do exactly that, at real
cost — see the cost log below). Real API auth means the factory's own orchestration endpoints
can't be driven by an unauthenticated caller impersonating any user.

**Verification that actually runs the thing.** Every milestone in this build was verified against
the real stack — real Postgres, real Keycloak logins, real Claude Agent SDK calls, real Docker
builds and running containers, a real two-user walkthrough for feature-request pickup — not just
unit tests against mocks. Several of the bugs listed in the decision log below (the git
dubious-ownership wall, the network topology gap, the owner-validation gap) only exist because
that live verification was done at all; none of them would have been caught by tests that mocked
the pieces that actually broke.

## Running

```
cp .env.example .env                                          # fill in ANTHROPIC_API_KEY
cp .streamlit/secrets.toml.example .streamlit/secrets.toml    # dev-only values, see Identity below
docker compose up --build
make gitea-init                                                # prints an access token
```

Paste the printed token into `.env` as `GITEA_TOKEN`, then:

```
docker compose up -d api                                       # picks up the new token
uv run alembic upgrade head
make seed
```

- API: http://localhost:8000/health
- UI: http://localhost:8501 (log in as `alice`/`alice`, `bob`/`bob`, `carol`/`carol`, or
  `dave`/`dave` — see `keycloak/realm-export.json`)
- Keycloak admin console: http://auth.localhost:8080 (`admin`/`admin`)
- Gitea: http://localhost:3000 (`factory` / whatever `GITEA_PASSWORD` you set, default
  `factory-dev-password`)

If your browser doesn't resolve `auth.localhost` to `127.0.0.1` automatically (most do, per the
`.localhost` TLD convention), add `127.0.0.1 auth.localhost` to your hosts file.

`GITEA_TOKEN` is deliberately *not* required at `docker compose up` time the way
`ANTHROPIC_API_KEY` is — generating it requires Gitea to already be running, so requiring it up
front would make it impossible to ever start Gitea. It's fine to be empty until the first build;
a missing token then surfaces as a real, actionable error rather than blocking every other service.

## Identity

Keycloak runs as a container with a small dev-only realm (`keycloak/realm-export.json`, fixture
users only — passwords match usernames). Streamlit's native OIDC (`st.login`) is the identity
provider; `app_owners.keycloak_sub` stores the real OIDC `sub` claim.

**Issuer hostname.** Keycloak is configured with `KC_HOSTNAME=auth.localhost` so the browser and
the `ui` container see the identical issuer. Without this, the browser reaches Keycloak at
`localhost:8080` while `ui` reaches it at `keycloak:8080`, and OIDC discovery/issuer validation
fails on the mismatch. The `ui` container resolves `auth.localhost` to the host via Docker's
`host-gateway` (`extra_hosts`), landing back on Keycloak's published port.

**API authentication.** `factory/api/auth.py` verifies a real Keycloak-issued bearer token on
every `/plans*` and `/builds*` request — signature checked against Keycloak's JWKS, issuer and
client (`azp`) checked against expected values — and derives the caller's identity from the
verified `sub` claim. Every endpoint also enforces that a run belongs to the verified caller
before allowing continuation, reads, or approval. The UI exposes the access token via
`expose_tokens = ["access"]` and forwards it as `Authorization: Bearer <token>`; evals
authenticate the same way, via `evals/keycloak_auth.py` fetching a real token per fixture user.

## Plan session

`factory/agents/plan_session.py` drives the real Claude Agent SDK, which is a thin Python wrapper
around the actual Node-based `claude` CLI run as a subprocess — the `api` image installs Node and
`@anthropic-ai/claude-code` for exactly this. The SDK is configured for isolation
(`setting_sources=[]`, `strict_mcp_config=True`) so it doesn't inherit a developer's local
`~/.claude` hooks/skills/plugins. **Only ever run or test this SDK from inside a container** —
never against a host-side Anthropic key.

Requires `ANTHROPIC_API_KEY` in `.env` (real, billed API calls). The 8-turn planner cap is
enforced by us (`Run.turns_used`), independent of the SDK's own per-connection `max_turns`, since
each HTTP request is a fresh SDK client resuming the session.

## Build + Review

`factory/agents/build_session.py` writes files only — no Bash, no network — and every Write/Edit
call is checked by a path-containment guard so the agent cannot touch anything outside its own
app directory. Bringing the container up is deterministic code (`container_runtime.py`, via
`docker-py`), never agent-driven.

Order is enforced in code: Build writes → required-files check + secrets scan (gitleaks, plus a
literal-value check for the factory's own API key) + static analysis (bandit + ruff `S` rules,
high-severity only blocks) → Review → only on a pass does anything get committed, pushed to
Gitea, or run as a container. One retry (2 attempts total) before a run is marked failed with the
accumulated findings.

The `api` container runs as root (needed for Docker socket access), so generated files are
chowned back to `HOST_UID`/`HOST_GID` (default `1000`/`1000`) once each attempt's outcome is
known — the chown has to happen *after* git operations, not before, since git itself runs as root
and refuses to operate on a repo it doesn't own if chowned to the host user first.

**Gitea.** The local working tree (`generated_apps/<slug>`) is the Docker build context and
Build's sandbox — real files on the host, inspectable regardless of push success. The durable,
clonable copy lives in Gitea (`factory/agents/gitea_client.py`): after a successful commit, the
orchestrator creates the repo (idempotently — a pickup's second push targets one that already
exists) and pushes over HTTP with a token embedded in the remote URL, never stored or logged.

**Network isolation.** Generated containers run on `factory-generated-net`, with no route to
Postgres or Keycloak; only `api` bridges both networks. `make eval-build` asserts this live by
attempting a connection from inside the running generated container and asserting it fails —
this check exists because the topology was wrong once (see the decision log).

## Register

Gate 2 (`POST /builds/{id}/approve`) is the only place an `App` row gets created —
`factory/registry/register.py` is plain code, not agent-driven. It creates the app, an `AppOwner`
(the original requester, as `business` owner), a `Capability` row per declared capability, and
backfills `app_id` onto the plan run, the build/review run, and their `CostEvent` rows.

## Feature request pickup

An app owner sees open requests against apps they own at `GET /feature-requests`. Picking one up
starts a normal Plan session seeded with the request's description, with `Run.app_id` set to the
target app at creation — that's the entire signal Build/Review/Register need to modify the
existing app instead of building a new one. Build writes into the existing repo; a failed retry
discards changes via `git checkout`/`clean`, never `rm -rf`. Register appends capabilities and
resolves the `FeatureRequest` instead of creating a new `App`.

Known gap, not yet fixed: if the pipeline fails *after* Gate 1's approval has already committed,
the plan is left "approved but never built" with no retry route through the API — needs an
idempotent approve or an explicit re-run path.

## Evals

Tier 2 — costs real money, run deliberately, never as part of `make test`:

```
make eval-routing    # 3 cases, one per Plan outcome
make eval-review     # 2 fixtures: a hardcoded secret, an injection risk
make eval-build      # one golden plan through the full pipeline + network isolation check
```

All three exec into the `api` container. `evals/routing_cases.yaml` holds a small representative
set; scaling to more cases is mechanical. Each case uses a `ScriptedRequester` — canned answers
keyed by keyword — to drive the multi-turn Plan session deterministically. `run_build_eval.py`
runs the real pipeline end to end and cleans up its own container, image, Gitea repo, generated
directory, and database rows regardless of pass/fail.

## Development

```
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```

Requires [`gitleaks`](https://github.com/gitleaks/gitleaks) on `PATH` (a single static binary) —
`factory/agents/secrets_scanner.py`'s tests call the real binary, matching the version pinned in
`Dockerfile.api`:

```
curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz \
  | tar -xz -C ~/.local/bin gitleaks   # or any directory already on PATH
```

`bandit` and `ruff` are ordinary Python dependencies (`uv sync` installs both) — `ruff` is a main
dependency, not dev-only, because Review calls it as a real product dependency (its `S` ruleset)
in addition to linting our own code.

## What to build next

<!-- left intentionally empty -->

## Decision and cost log

### Key decisions

| Decision | Choice | Rejected alternatives and why |
|---|---|---|
| Registry manifest storage | Postgres `jsonb` manifest + relational rows for capabilities/owners | Pure jsonb with no extracted columns — rejected because duplicate detection and scope comparison need to be plain SQL, not jsonb path expressions, to stay deterministic and testable. |
| Identity | Real Keycloak container + realm, Streamlit native OIDC | A mock identity selector (no real auth) — rejected once the plan explicitly ruled it out in favor of demonstrating that routing names an owner Keycloak actually verifies. |
| Blueprint scope | Numeric complexity score (1–5) with an anchored rubric and worked examples, injected as ground truth | A bare score with no anchoring — rejected as too prone to drift between runs with nothing to check it against. |
| Build/Review topology | Two sequential SDK sessions (Build, Review), orchestrated by our own code | One SDK session with Build/Review as SDK-native subagents — this was the original design; changed deliberately (your call, not mine) because caps and per-stage cost tracking are simpler as code-level orchestration than as SDK subagent dispatch. |
| Secrets scanning | gitleaks (subprocess, maintained pattern library) + a bespoke literal-value check for the factory's own key | Hand-rolled regexes (my first pass — correctly called out as reinventing a solved problem); detect-secrets (pure Python, no live-verification); TruffleHog (adds live credential verification, which doesn't help here since generated apps should never contain a real credential regardless of validity). |
| Static analysis in Review | bandit + ruff's `S` ruleset, high-severity blocks the pipeline | LLM-only review (my original implementation — correctly called out as "lazy," since a tool exists for exactly this and inline judgment alone missed a class of findings a deterministic tool catches every time). |
| Generated-app hosting | Gitea (self-hosted git server), local disk as the Docker build context / working tree only | Plain disk as the only artifact (my original implementation) — changed because a directory on a bind mount isn't a real push/pull/clone workflow with access control, which is what "code lands somewhere humans can edit it" should actually mean. |
| Python version | 3.13 everywhere (factory images and generated-app images) | 3.12 (my original, unconsidered default) — no compatibility reason to prefer it; changed once actually asked. |
| Cost accounting | Per-stage, per-model `CostEvent` rows, backfilled onto the `App` at registration | A single total-per-run number — rejected because it hides which stage is expensive, which is exactly the information worth having. |

### Where I was led astray, and how it was caught

- **An unreviewed security call written into documentation as if it were a decided one.** After
  M3, the README described the API trusting a client-supplied identity as an "acceptable POC
  trust boundary" — a call I made unilaterally and then cited as settled fact. A later security
  review flagged the resulting endpoints as genuinely exploitable (any network caller could
  impersonate any user and trigger real Docker builds on the host), and you called out the
  deeper problem directly: I'd made the decision *and* written the justification for it, with no
  actual check in between. Fixed with real Keycloak bearer-token verification; the practice
  fixed was "don't let your own prior unchecked note become the evidence for the next decision."
- **A secret nearly written to disk the wrong way.** Asked to store a real API key in `.env`, I
  used a Bash heredoc instead of the Write tool specifically to "avoid printing it" — which
  backfired, since the harness's file-change-detection echoes the full diff of any file changed
  outside its own tools, printing the key anyway. You caught this immediately and it's now a hard
  rule in `CLAUDE.md`: secrets only ever go through Write/Edit, never a shell redirect.
- **The Agent SDK silently inheriting a whole unrelated environment.** Early live testing of the
  Plan session ran from inside my own Claude Code session rather than a container, which meant
  the SDK's spawned `claude` subprocess inherited every hook, skill, and MCP plugin from that
  session — burning ~15,800 cache-creation tokens and real money on a single one-word "ping" test
  that should have cost a few cents. You noticed the leftover subprocess still running, asked
  directly why the CLI was involved at all (a fair question — it wasn't a workaround, it's how
  the SDK is implemented), and set the standing rule: SDK work only ever runs inside a container
  from here on.
- **A batch of design decisions made and shipped without being asked.** After M7, a manual review
  surfaced a cluster of calls I'd made alone: no live test of the network-isolation fix, plain
  disk instead of a real git server, an unconsidered Python version, LLM-only review with no
  static-analysis tool, a redundant naming convention, and docstring-style comments used as plain
  inline notes. None were hidden, but none were asked about either. All were fixed in the same
  pass this log describes, several by asking first this time.
- **A stale-data bug this session caught on its own**, worth including because it's the same
  category of mistake caught differently: hardening owner-validation logic (added after the
  hallucination bug above) accepted *any* value already sitting in `app_owners` as proof of
  legitimacy — including leftover non-UUID rows from testing done before real auth existed. A
  live eval regression surfaced it; the fix requires a valid owner to be UUID-shaped, not merely
  "present in the table," so old bad data can never again validate a new bad answer.

### Cost log

There is no single authoritative ledger — `cost_events` rows get deleted along with their test
apps during cleanup, and the registry itself was reset (fresh volumes) several times over the
course of this build. What follows is reconstructed from figures actually observed during live
verification, not invented after the fact.

**Representative real figures, observed live:**
- One full plan → build → review cycle for a small app (2 capabilities, 1 attempt): typically
  **$0.15–0.35** total, split roughly evenly across the plan turn, the build turn, and the review
  turn, each of which uses two models (the SDK auto-routes some sub-calls to Haiku, the rest to
  Sonnet).
- A feature-request pickup (a second plan → build → review cycle against an existing app):
  roughly the same again, since it's a second full cycle, not an incremental one.
- The isolation bug above cost **$0.0637 for a single "ping"** — normal turns after the fix cost
  a few cents each. That's roughly an 8–10× overhead from one unisolated call, which is the
  single clearest example in this project of a reliability bug and a cost bug being the same bug.
- Each `make eval-routing` run (3 live Plan conversations) cost roughly **$0.15–0.25**; each
  `make eval-build` run (one full pipeline cycle plus container lifecycle checks) roughly
  **$0.15–0.35**; `make eval-review` is cheapest, one Review call per fixture, a few cents each.

**Rough total for this entire session** (every milestone's live verification, every eval run,
every regression check, every re-run after a bug fix): most plausibly in the **low single-digit
dollars** — call it $3–6 — accumulated over roughly a dozen full or partial pipeline runs plus
repeated eval invocations. This is a POC verified unusually thoroughly (live at every milestone,
not just unit-tested), which multiplies the run count well above what a single production
request would cost; the plan's own target of "a few dollars per end-to-end run" describes one
run, not a whole build-and-verify session like this one.

**What I'd optimize next:**
- **Prompt caching discipline.** The planner's registry digest and blueprint text are rebuilt and
  resent on every turn; keeping that content byte-identical across turns of the same session (and
  ideally across sessions, until the registry actually changes) would raise the cache-hit rate on
  the largest fixed part of the prompt.
- **Tighter per-stage token budgets.** `build_max_turns=30` is generous headroom for a blueprint
  that only ever produces four files; a smaller ceiling would cost nothing in practice and cap
  the worst case harder.
- **Batch eval runs instead of one-off.** Running `eval-routing`, `eval-review`, and `eval-build`
  back to back inside the same container process (rather than three separate `docker compose
  exec` invocations, as today) would let the SDK's own session/connection reuse do more of the
  caching work instead of starting cold each time.
- **Fix the isolation class of bug for good.** The single most expensive mistake in this project
  was environmental, not a prompting problem — a pre-flight check that fails fast if
  `setting_sources`/`strict_mcp_config` aren't set, or if the SDK subprocess's environment looks
  larger than expected, would catch the next version of this before it burns real money rather
  than after.
