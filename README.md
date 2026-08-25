# App Factory

## What this is

A platform where a business user describes an internal app in plain language, and the system
plans it, builds it, reviews it, and registers it — with a named owner and a recorded cost —
without an engineer writing any code. The user talks to an interactive planner. A human approves
the plan before anything is built, and approves the finished app before it's registered. The
result is a small, running application and a permanent, searchable record of what exists, what
it does, what it cost, and who is responsible for it.

The point of this project is the process and the record it produces, not how sophisticated the
generated apps are. Generated apps are deliberately small (one pattern: a Streamlit app running
in Docker). The engineering effort went into planning, building, reviewing, gating, and
accounting for those apps safely and repeatably.

## Why an organization would want this

Most organizations end up with small internal tools nobody can account for: a spreadsheet
replacement a manager had built two years ago, a script someone in operations still runs, an app
whose original author no longer works there. Nobody can say what it costs, who owns it, or
whether something similar already exists. The same small tool gets rebuilt by different teams,
and nothing gets retired with confidence because nobody knows what depends on it.

This platform answers those questions directly, as apps are created, instead of requiring someone
to investigate later:

- **Every app has a named owner** from the moment it's requested — a real, verified identity
  (Keycloak), not a shared mailbox or an account that belongs to someone who has left.
- **Every app's cost is recorded** at each stage (planning, building, reviewing) as it's built,
  not estimated afterward.
- **A duplicate request is routed to the person who already owns the existing app**, instead of
  producing a fourth copy of the same tool.
- **Changes to an existing app go through its owner**, so new capabilities and their cost are
  recorded against the same app instead of becoming an untracked, separate copy.
- **Scope is limited by a fixed rule, not by judgment call** — a numeric limit on how complex a
  request can be stops a single request from covering something that should instead go through a
  real design conversation with a person.

The generated apps themselves don't need to be impressive for this to work. What matters is that
the record the system produces is accurate.

## Architecture

```
Plan (interactive session)                    Build + Review (one orchestrator, two subagents)
  └─ proceed / route_to_human / feature_request  └─ write files → gate → review → retry (×1)
       │ [HUMAN GATE 1: approve, before spend]         │ [HUMAN GATE 2: approve, before registration]
       ▼                                                ▼
  Register (plain code, no LLM) — creates the App row, owner, capabilities; records cost
```

The Docker Compose stack has five services: **Postgres** (the registry database), **Keycloak**
(identity), **Gitea** (a self-hosted git server for generated apps), **api** (FastAPI, runs the
pipeline), and **ui** (Streamlit). Generated apps run in their own containers on a separate
Docker network, built and started by ordinary code — never by the model — against the host's
Docker socket.

### How reliability was built in

The reliability of this system doesn't come from more careful prompting. It comes from moving as
many checks as possible out of the model's judgment and into code that runs before the model acts,
plus requiring a human decision at the two points where a mistake would be expensive or hard to
undo.

**Checks that don't depend on the model's judgment run first, and run before the model gets a
say:**
- Every file Build writes is checked by code that resolves the path and confirms it's still
  inside the app's own directory. This isn't a prompt instruction; it's a permission check the
  model cannot bypass by being told something different.
- Every generated app is scanned by gitleaks (a maintained tool for finding secrets by pattern),
  by a separate check for the literal value of this system's own live API key, and by bandit and
  ruff's security rules for Python-specific problems — all before the model doing the review ever
  reads the code. A high-severity result from any of these stops the pipeline outright. The
  model's own review only runs on code that has already passed every check that doesn't need
  judgment at all.
- The planner is never trusted to correctly report whether a request duplicates an existing app
  using only a single lookup call it might get wrong. It's given the full list of registered
  apps, their capabilities, and their owners as text, and told directly that a lookup returning no
  match does not mean there's no duplicate.
- Free-text values the model is asked to repeat back are exactly where it invents things: during
  testing, it invented a blueprint identifier that doesn't exist, and separately named a real
  user by a plain username instead of their actual account identifier. Both problems are now
  prevented in code: the blueprint identifier is filled in by the orchestrator and never asked of
  the model at all, and any named owner is checked against the app's real, verified owners before
  being accepted — if it doesn't match a real owner, a real one is substituted.

**Two separate approval points, not one.** Approving the plan (before anything is built) and
approving the finished app (before it's permanently recorded) are different decisions with
different consequences. Combining them into one approval would mean a human can't stop a bad plan
before money is spent, or can't stop a working app they don't want permanently recorded.

**Fixed limits on turns, retries, and scope.** The planner stops after 8 exchanges rather than
continuing indefinitely. Build and Review get one retry (two attempts total) before reporting a
clear failure instead of retrying forever. A numeric limit on how complex a request can be means
a request that's too large is routed to a person instead of being built anyway.

**Network isolation that's checked, not just configured.** Generated containers run on a network
with no route to Postgres or Keycloak. This is checked automatically: one of the automated tests
attempts a network connection from inside a real generated container to those services and
confirms it fails, rather than only trusting that the configuration is correct. The Claude Agent
SDK itself is run with settings that stop it from picking up a developer's own local tool
configuration — an early bug let it do exactly that, at real cost (see the cost section below).
Every API request is checked against a real, verified login token, so the system's own endpoints
can't be used by someone pretending to be another user.

**Every stage was actually run, not just tested against a stand-in.** Each part of this system was
checked against the real thing it depends on — a real Postgres database, a real Keycloak login, a
real call to the Claude Agent SDK, a real Docker build and a real running container, a full
two-person walkthrough of one user filing a request against another user's app. Several of the
bugs listed in the decision log below (a git ownership error, a network configuration gap, an
owner-validation gap) were only found because of this; none of them would have been caught by
tests that stood in for the real systems instead of using them.

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

If your browser doesn't resolve `auth.localhost` to `127.0.0.1` on its own (most do, since
`.localhost` is reserved to always mean the local machine), add `127.0.0.1 auth.localhost` to
your hosts file.

`GITEA_TOKEN` is not required at `docker compose up` time the way `ANTHROPIC_API_KEY` is, because
generating it requires Gitea to already be running — requiring it up front would make it
impossible to ever start Gitea in the first place. It's fine for it to be empty until the first
build; a missing token then causes a clear, specific error at that point instead of blocking every
other service from starting.

## Identity

Keycloak runs as a container with a small realm meant only for this project
(`keycloak/realm-export.json`, fixture users only — each password matches its username).
Streamlit's built-in login (`st.login`) is the identity provider; `app_owners.keycloak_sub` stores
the real, verified subject identifier from that login.

**Issuer hostname.** Keycloak is configured with `KC_HOSTNAME=auth.localhost` so the browser and
the `ui` container reach it at the same address. Without this, the browser would reach Keycloak
at `localhost:8080` while `ui` reached it at `keycloak:8080`, and login verification would fail
because the two addresses don't match. The `ui` container resolves `auth.localhost` to the host
machine through Docker's `host-gateway` setting, landing back on Keycloak's published port.

**API authentication.** `factory/api/auth.py` checks a real Keycloak login token on every
`/plans*` and `/builds*` request — its signature is checked against Keycloak's public keys, and
its issuer and client are checked against expected values — and the caller's identity comes from
that verified token, not from anything the caller supplies directly. Every endpoint also checks
that a run belongs to the verified caller before allowing it to be continued, read, or approved.
The UI reads the login token via `expose_tokens = ["access"]` and sends it as
`Authorization: Bearer <token>` on every request; the automated evaluation scripts log in the same
way, using `evals/keycloak_auth.py` to get a real token for each fixture user rather than
bypassing the check.

## Plan session

`factory/agents/plan_session.py` calls the real Claude Agent SDK, which runs the actual Node-based
`claude` command-line tool as a subprocess — the `api` image installs Node and
`@anthropic-ai/claude-code` for exactly this. The SDK is configured so it does not read a
developer's own local configuration (`setting_sources=[]`, `strict_mcp_config=True`). **Only ever
run or test this SDK from inside a container** — never with a personal API key on a development
machine.

Requires `ANTHROPIC_API_KEY` in `.env` (this makes real, billed API calls). The 8-turn limit on
the planner is enforced by this project's own code (`Run.turns_used`), separately from the SDK's
own per-connection turn limit, because each HTTP request starts a new SDK connection that resumes
the same underlying session.

## Build + Review

`factory/agents/build_session.py` only writes files — it has no shell access and no network
access, and every file write is checked against the app's own directory before it's allowed.
Starting the container is ordinary code (`container_runtime.py`, using `docker-py`), never
something the model does directly.

The order of operations is fixed in code: Build writes files, then a required-files check plus a
secrets scan (gitleaks, plus a check for the literal value of this system's own API key) plus
static analysis (bandit and ruff's security rules; only high-severity results block the pipeline)
all run, then Review runs, and only after Review passes does anything get committed, pushed to
Gitea, or run as a container. One retry (two attempts total) is allowed before a run is marked
failed, with the accumulated findings recorded.

The `api` container runs as root (this is required for Docker socket access), so generated files
are changed to be owned by `HOST_UID`/`HOST_GID` (default `1000`/`1000`) once each attempt's
outcome is known — this has to happen after the git operations, not before, because git itself
runs as root and refuses to operate on a repository it doesn't own if it's already been changed to
a different owner.

**Gitea.** The local working directory (`generated_apps/<slug>`) is what Docker builds from and
what Build writes into — real files on the host, so they can be inspected whether or not the push
to Gitea succeeds. The permanent copy that a person would actually clone lives in Gitea
(`factory/agents/gitea_client.py`): after a successful commit, the pipeline creates the repository
if it doesn't already exist, then pushes over HTTP with a login token that's used once for that
push and never written to the repository's own configuration file or shown in an error message.

**Network isolation.** Generated containers run on `factory-generated-net`, which has no route to
Postgres or Keycloak; only `api` is connected to both networks. `make eval-build` checks this
directly by attempting a connection from inside the running generated container and confirming it
fails — this check exists because the network configuration was wrong once (see the decision log).

## Register

The second approval (`POST /builds/{id}/approve`) is the only place an `App` row gets created —
`factory/registry/register.py` is ordinary code, not something the model runs. It creates the
app, an `AppOwner` record (the original requester, recorded as the `business` owner), a
`Capability` record for each capability the plan declared, and updates the plan run, the
build/review run, and their `CostEvent` records with the new app's identifier.

## Feature request pickup

An app owner sees open requests against apps they own at `GET /feature-requests`. Picking one up
starts a normal Plan session using the request's description as the opening message, with
`Run.app_id` set to the target app when the run is created — that one field is the only signal
Build, Review, and Register need to modify the existing app instead of building a new one. Build
writes into the app's existing files; if a retry is needed, the failed attempt's changes are
discarded with `git checkout`/`git clean`, never by deleting and recreating the directory.
Register adds the new capability to the existing app and marks the request resolved, instead of
creating a new app.

Known gap, not yet fixed: if the pipeline fails after the first approval has already been recorded,
the plan is left in an approved-but-unbuilt state with no way to retry it through the API — this
needs either a way to safely repeat the approval or a separate retry action.

## Evals

These call a real model and cost real money — run them deliberately, never as part of
`make test`:

```
make eval-routing    # 3 cases, one per Plan outcome
make eval-review     # 2 fixtures: a hardcoded secret, an injection risk
make eval-build      # one full plan through the pipeline, plus the network isolation check
```

All three run inside the `api` container. `evals/routing_cases.yaml` holds a small set of cases;
adding more is mechanical. Each case uses a `ScriptedRequester` — canned answers matched by keyword
— to answer the planner's questions automatically. `run_build_eval.py` runs the real pipeline
start to finish and removes its own container, image, Gitea repository, generated directory, and
database rows afterward, whether it passed or failed.

## Development

```
uv sync
uv run ruff format .
uv run ruff check .
uv run pytest
```

Requires [`gitleaks`](https://github.com/gitleaks/gitleaks) on your `PATH` (a single binary with
no other dependencies) — `factory/agents/secrets_scanner.py`'s tests call the real program rather
than a stand-in, matching the version installed in `Dockerfile.api`:

```
curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz \
  | tar -xz -C ~/.local/bin gitleaks   # or any directory already on PATH
```

`bandit` and `ruff` are regular Python dependencies (`uv sync` installs both). `ruff` is listed as
a main dependency rather than a development-only one because Review actually calls it (its
security rules) as part of the running system, not only for checking this project's own code.

## What to build next

<!-- left intentionally empty -->

## Decision and cost log

### Key decisions

| Decision | Choice | What was considered and rejected, and why |
|---|---|---|
| Registry storage | Postgres, with the raw plan stored as a `jsonb` column and capabilities/owners stored as their own rows | Storing everything only as `jsonb` with no separate rows — rejected because duplicate detection and scope comparison need to be plain, indexable queries, not searches through a JSON document, to stay predictable and testable. |
| Identity | A real Keycloak container and realm, using Streamlit's built-in login | A selector that lets a user pick who they're pretending to be, with no real login — rejected in favor of a real, verifiable identity, since naming a specific owner only means something if that identity is real. |
| Blueprint scope limit | A numeric complexity score from 1 to 5, with a written description and worked examples for each level, given to the planner as reference text | A bare number with nothing explaining what it means — rejected as too likely to be scored inconsistently between runs with nothing to check it against. |
| Build/Review structure | Two separate Claude Agent SDK sessions (Build, then Review), controlled by this project's own code | One SDK session with Build and Review as subagents inside it — this was the original plan; changed on request, because turn limits and per-stage cost tracking are simpler to implement as code controlling two sessions than as the SDK's own subagent handling. |
| Secrets scanning | gitleaks, plus a separate check for the literal value of this system's own live API key | Regular expressions written by hand for this project (the first version — correctly pointed out as redoing work a maintained tool already does well); detect-secrets (a Python library with no way to check whether a found value is a real, currently valid credential); TruffleHog (checks whether a found credential is currently valid, which doesn't help here, since a generated app should never contain a real credential regardless of whether it's still valid). |
| Static analysis in Review | bandit and ruff's security rules, where a high-severity result blocks the pipeline | Review done only by the model reading the code (the first version — correctly pointed out as an easy shortcut, since a maintained tool exists for exactly this and the model alone missed a category of problems a fixed tool catches every time). |
| Where generated apps are stored | Gitea (a self-hosted git server); local disk is only the working copy Build writes into and Docker builds from | Local disk as the only copy (the first version) — changed because a directory on the host isn't a real way for a person to clone, push, and control access to the code; a real git server is. |
| Python version | 3.13, used everywhere (this project's own images and the generated apps' images) | 3.12 (the original choice) — there was no actual reason to prefer 3.12; it was simply the first version picked, without being asked. |
| Cost tracking | A separate record for each stage and each model used, attached to the app once it's registered | One combined number per run — rejected because it hides which stage is expensive, which is the useful part of tracking cost at all. |

### Where a mistake was made, and how it was caught

- **A security decision written into the documentation as if it had already been settled.** After
  an early version of this project, the documentation described the API accepting a caller's
  claimed identity without checking it, and called this an acceptable limitation for a
  proof-of-concept. That description was written by me, without being checked with anyone, and
  then treated as a settled fact in later work. A security review later found that this made the
  API's endpoints genuinely exploitable — anyone who could reach the API could claim to be any
  user and trigger real builds on the host. The deeper problem was pointed out directly: a
  decision and its own justification had both been written by the same unchecked process, with
  nothing in between. This is fixed now, with real login token verification on every request.
- **A secret nearly written to a file the wrong way.** Asked to put a real API key into a `.env`
  file, I used a shell command instead of the file-editing tool, specifically to avoid printing
  the key — which had the opposite effect, because this tool's file-change detection shows the
  full contents of any file changed outside its own editing tools, so the key was printed anyway.
  This was caught immediately, and there is now a fixed rule for this project: a real secret only
  ever goes into a file through the editing tool directly, never through a shell command.
  
  **A note on this key specifically:** this incident happened with the real, currently-active API
  key for this account. Because the key was never sent anywhere outside this machine and the
  provider that already legitimately holds it, the actual increase in risk was limited to it
  appearing in this machine's own local session records — but it could not be rotated afterward,
  which is exactly the situation this rule exists to prevent.
- **The Agent SDK picking up an entire unrelated setup it shouldn't have had access to.** Early
  testing of the Plan session was run from inside my own development session instead of inside a
  container. This meant the SDK's own subprocess picked up every tool, skill, and plugin
  configured for that development session — using around 15,800 tokens of context and real money
  on a single one-word test that should have cost a few cents. A leftover process was still running
  afterward; this was noticed, a direct question was asked about why a command-line tool was
  involved at all (a reasonable question — it wasn't a shortcut I took, it's how the SDK is
  actually implemented), and a standing rule was set: this SDK is only ever run inside a container
  from that point on.
- **A group of decisions made and shipped without being asked about first.** After an early
  working version of the whole pipeline, a manual review found several choices made without
  checking first: no automated test that the network configuration change actually worked, plain
  disk used instead of a real git server, a Python version picked without thinking about it,
  review done by the model alone with no separate tool, a naming convention that repeated the same
  value twice for no reason, and comments written as one-line quoted text after a value instead of
  as a plain comment. None of these were hidden, but none were raised for a decision either. All
  were fixed in one pass, several of them properly asked about this time before being changed.
- **A stale-data problem found without anyone else pointing it out.** Worth including because it's
  the same kind of mistake, caught a different way: the code that checks whether a named owner is
  real was written to accept any value that already appeared in the owner records — including old,
  leftover entries written during testing, before real login-based identity existed. A routine
  check during later testing turned up a case where an old, non-identity-shaped entry let a wrong
  answer pass as if it were real. The fix requires an owner value to actually look like a real,
  verified identity, not merely appear somewhere in the existing records, so old bad data can't
  make a new bad answer look correct again.

### Cost log

Money was spent in two different places against the same API key, and they need to be counted
separately before they can be added together.

**1. The factory's own model calls — planning, building, reviewing generated apps.** These are
recorded in the `cost_events` table as they happen, per model call, so these figures are exact,
not estimated:
- One complete plan-build-review cycle for a small app (two capabilities, one attempt, no
  retries): typically **$0.15 to $0.35** in total, split roughly evenly across the planning step,
  the build step, and the review step. Each of these steps uses two different models — the SDK
  automatically sends some smaller sub-requests to a cheaper model and the main work to a larger
  one.
- Picking up and building a feature request against an existing app costs about the same again,
  since it's a second complete cycle, not a partial one.
- The environment-isolation problem described above cost **$0.0637 for a single one-word test** —
  ordinary turns after that was fixed cost a few cents each. That's roughly 8 to 10 times more
  than it should have, from a single avoidable mistake, and it's the clearest example in this
  project of the same problem being both a reliability issue and a cost issue.
- Each run of `make eval-routing` (three real planner conversations) cost roughly **$0.15 to
  $0.25**. Each run of `make eval-build` (one full pipeline cycle, plus starting and checking a
  container) cost roughly **$0.15 to $0.35**. `make eval-review` is the cheapest of the three, one
  model call per test case, a few cents each.
- Across every stage checked against the real system while it was being built, every automated
  evaluation run, and every re-run after fixing a bug, this side of the ledger — the thing this
  project actually builds — comes to roughly **$3 to $6** in total. A single real request going
  through the whole process, start to finish, costs well under a dollar.

**2. The work of building the factory itself — this coding session.** For most of the time this
project was being built, the assistant writing this code was itself running against the same API
key, so that usage counts against the same total. Claude Code's own session log gives an exact
token count for that: 25 sessions, 1,087 model calls, about 505 million input tokens (98% of which
were served from cache, not billed at full price) and about 620,000 output tokens. Pricing that
usage at the rate for the model used for most of it (Sonnet 5) gives a total of roughly **$125 to
$135**. That number is an estimate, not an exact figure like the ones above — a smaller number of
calls early on used a more expensive model for planning, and one advisor call used a different
model still, and the token log doesn't break spend down by model, so those calls push the true
number somewhat above this baseline rather than below it.

**Combined**, the total cost against this API key for the whole engagement — writing the factory,
plus everything the factory itself spent doing its job — is roughly **$130 to $165**. The
overwhelming majority of that is the cost of the coding work itself, not the system it produced.
That's expected for a project this size worked interactively over one long session, but it's worth
being explicit about: the "$3 to $6" figure is what this system costs to *operate*, and it is a
small fraction of what it cost to *build*.

**What would reduce this cost further:**
- **Reuse identical prompt content across turns.** The text given to the planner describing the
  registered apps and the blueprint rules is rebuilt and resent on every turn. Keeping that text
  identical across turns of the same conversation, and ideally across separate conversations until
  the registry actually changes, would let the model provider's prompt caching apply to more of
  the request instead of treating it as new content each time.
- **Lower the per-stage limits.** The build step currently allows up to 30 internal turns, which
  is far more than is ever needed to produce four files. A lower limit would cost nothing in
  practice and would cap the worst case more tightly.
- **Run evaluations together instead of separately.** `eval-routing`, `eval-review`, and
  `eval-build` are currently three separate commands, each starting its own connection to the
  model. Running them one after another inside the same process would let the model provider's
  own caching carry over between them instead of starting cold each time.
- **Catch environment-isolation mistakes automatically.** The single most expensive mistake in
  this project's own operating cost was not a prompting problem — it was an environment
  configuration problem. A check that fails immediately and clearly if the SDK's isolation
  settings aren't in place, or if the SDK's subprocess environment looks larger than expected,
  would catch the next version of this mistake before it costs money instead of after.
- **On the coding-session side, the much larger cost:** almost all of the ~505 million input
  tokens were cache reads, which is the caching system working as intended, not waste — but the
  volume still points at a real lever: fewer, more targeted file reads and fewer long-running
  agent turns per milestone would cut the number of times context gets rebuilt and re-sent. The
  single highest-leverage change for a project like this would be scoping work into smaller,
  more separable sessions so each one carries less accumulated history.
