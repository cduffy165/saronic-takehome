"""Runs one turn of the interactive Plan session against the real Claude Agent SDK.

Each HTTP request maps to one planner turn: a fresh ``ClaudeSDKClient`` resumes
the SDK's own session (by id) rather than staying connected across requests, so
the 8-turn cap is enforced by us against a ``turns_used`` counter persisted on
the ``Run`` row — the SDK's own ``max_turns`` only bounds a single connection,
which here is always one exchange.

The planner ends by calling exactly one of three tools (``submit_plan_proceed``,
``submit_plan_route_to_human``, ``submit_plan_feature_request``); anything else
it says is a clarifying question shown back to the requester.
"""

from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)
from pydantic import ValidationError

from factory.agents.blueprint import Blueprint, render_scale_for_prompt
from factory.agents.plan_schema import (
    CHECK_REGISTRY_OVERLAP_TOOL,
    SUBMIT_PLAN_FEATURE_REQUEST_TOOL,
    SUBMIT_PLAN_PROCEED_TOOL,
    SUBMIT_PLAN_ROUTE_TO_HUMAN_TOOL,
    FeatureRequestArgs,
    FeatureRequestOutcome,
    ProceedArgs,
    ProceedOutcome,
    RouteToHumanArgs,
    RouteToHumanOutcome,
)
from factory.agents.planner_settings import get_planner_settings
from factory.registry.db import get_session_factory
from factory.registry.queries import find_apps_by_capability_slugs, list_apps

SERVER_NAME = "factory_planner"


@dataclass
class PlannerTurnResult:
    reply_text: str
    outcome: dict[str, Any] | None
    model_usage: dict[str, Any] = field(default_factory=dict)


def _render_registry_digest(session: Any) -> str:
    """A ground-truth summary of active apps for the planner's own overlap
    judgment. check_registry_overlap only does exact capability-slug matching,
    which is unreliable against a model-guessed slug that just phrases the same
    capability differently — a no-match there is not proof of no overlap. The
    digest is what lets the model reason about semantic overlap directly."""
    apps = list_apps(session)
    if not apps:
        return "The registry currently has no active apps."
    lines = ["Currently registered apps (this is ground truth — use it to judge overlap):"]
    for app in apps:
        owners = (
            ", ".join(f"{o.keycloak_sub} ({o.role})" for o in app.owners) or "no owners recorded"
        )
        capabilities = (
            ", ".join(f"{c.slug} ({c.description})" for c in app.capabilities) or "none listed"
        )
        lines.append(
            f"- {app.slug} — {app.name}: {app.purpose}\n"
            f"    capabilities: {capabilities}\n"
            f"    owners: {owners}"
        )
    return "\n".join(lines)


def _render_pickup_context(target_app: Any) -> str:
    capabilities = (
        ", ".join(f"{c.slug} ({c.description})" for c in target_app.capabilities) or "none listed"
    )
    return f"""This is a feature-request pickup, not a new app: the owner is fulfilling a
change already requested against an app that exists in the registry.

- {target_app.slug} — {target_app.name}: {target_app.purpose}
- Existing capabilities: {capabilities}

Scope your questions and your eventual {SUBMIT_PLAN_PROCEED_TOOL} call to ONLY the new
capability being added — set ``capabilities`` to just the new one(s), not a restatement
of the existing list, and set ``name``/``purpose`` to describe the change itself. If the
requested change is too large for the blueprint's scope even as an addition, use
{SUBMIT_PLAN_ROUTE_TO_HUMAN_TOOL} instead. {SUBMIT_PLAN_FEATURE_REQUEST_TOOL} does not
apply here — this session exists because that step already happened."""


def _build_system_prompt(blueprint: Blueprint, registry_digest: str, target_app: Any = None) -> str:
    pickup_block = f"\n\n{_render_pickup_context(target_app)}" if target_app is not None else ""
    return f"""You are the Plan stage of an internal app factory. A business user is
requesting a small internal app. Gather enough detail to reach one of three
outcomes, then finish by calling exactly one of these tools:

- {SUBMIT_PLAN_PROCEED_TOOL}: the request fits the blueprint below (there is
  only this one blueprint — you don't need to name it) and doesn't overlap an
  existing registered app.
- {SUBMIT_PLAN_ROUTE_TO_HUMAN_TOOL}: the request overlaps an existing app, or
  exceeds the blueprint's scope rating, or no blueprint fits at all. owner_sub
  must be a real Keycloak subject from the registry digest below — for an
  overlap, use one of the overlapping app's own owners; never invent one.
  Name the reason, and recommend a conversation — never a flat refusal.
- {SUBMIT_PLAN_FEATURE_REQUEST_TOOL}: the request is a change to an app that
  already exists in the registry, not a new app.

Judge overlap primarily against the registry digest below, not just the
{CHECK_REGISTRY_OVERLAP_TOOL} tool — that tool only matches exact capability
slugs, so a "no match" result does not by itself mean there's no overlap; the
same capability can be phrased as a different slug. Use the tool as a
supplementary check, but trust your own reading of the digest for the
overlap decision.

You are recommending, not deciding: a human approves the plan before anything
is built, so never say a plan is "approved" or that build has started.

Ask clarifying questions in plain text until you have enough to score the
request against the blueprint's scale and to judge overlap. Be direct and
brief; this is a business user, not an engineer.

{render_scale_for_prompt(blueprint)}

{registry_digest}{pickup_block}
"""


def _make_tools(captured: dict[str, Any], blueprint_id: str) -> Any:
    @tool(
        CHECK_REGISTRY_OVERLAP_TOOL,
        "Check whether any registered app already declares capabilities like these.",
        {"capability_slugs": list[str]},
    )
    async def check_registry_overlap(args: dict[str, Any]) -> dict[str, Any]:
        session_factory = get_session_factory()
        with session_factory() as session:
            apps = find_apps_by_capability_slugs(session, args["capability_slugs"])
        if not apps:
            text = (
                "No exact capability-slug match. This does NOT rule out overlap — "
                "compare the request against the registry digest in your instructions, "
                "which is the ground truth for this decision."
            )
        else:
            lines = [
                f"- {app.slug} ({app.name}); owners: "
                + ", ".join(o.keycloak_sub for o in app.owners)
                for app in apps
            ]
            text = "Overlapping apps found:\n" + "\n".join(lines)
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        SUBMIT_PLAN_PROCEED_TOOL,
        "Finalize the plan: proceed to build.",
        ProceedArgs.model_json_schema(),
    )
    async def submit_plan_proceed(args: dict[str, Any]) -> dict[str, Any]:
        return _capture(
            captured, "proceed", ProceedArgs, ProceedOutcome, args, blueprint_id=blueprint_id
        )

    @tool(
        SUBMIT_PLAN_ROUTE_TO_HUMAN_TOOL,
        "Finalize the plan: route the requester to a named human owner instead of building.",
        RouteToHumanArgs.model_json_schema(),
    )
    async def submit_plan_route_to_human(args: dict[str, Any]) -> dict[str, Any]:
        return _capture(captured, "route_to_human", RouteToHumanArgs, RouteToHumanOutcome, args)

    @tool(
        SUBMIT_PLAN_FEATURE_REQUEST_TOOL,
        "Finalize the plan: file this as a feature request against an existing app.",
        FeatureRequestArgs.model_json_schema(),
    )
    async def submit_plan_feature_request(args: dict[str, Any]) -> dict[str, Any]:
        return _capture(
            captured, "feature_request", FeatureRequestArgs, FeatureRequestOutcome, args
        )

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        tools=[
            check_registry_overlap,
            submit_plan_proceed,
            submit_plan_route_to_human,
            submit_plan_feature_request,
        ],
    )


def _capture(
    captured: dict[str, Any],
    outcome_kind: str,
    args_model: type,
    outcome_model: type,
    args: dict[str, Any],
    **extra_fields: Any,
) -> dict[str, Any]:
    try:
        validated = args_model.model_validate(args)
    except ValidationError as exc:
        return {
            "content": [{"type": "text", "text": f"Invalid {outcome_kind} payload: {exc}"}],
            "is_error": True,
        }
    outcome = outcome_model(**validated.model_dump(), **extra_fields)
    captured["outcome"] = outcome.model_dump()
    return {"content": [{"type": "text", "text": "Plan recorded."}]}


async def run_planner_turn(
    *,
    session_id: str,
    is_first_turn: bool,
    user_message: str,
    blueprint: Blueprint,
    target_app: Any = None,
) -> PlannerTurnResult:
    settings = get_planner_settings()
    session_factory = get_session_factory()
    with session_factory() as registry_session:
        registry_digest = _render_registry_digest(registry_session)

    captured: dict[str, Any] = {}
    server = _make_tools(captured, blueprint.id)
    qualified_tools = [
        f"mcp__{SERVER_NAME}__{name}"
        for name in (
            CHECK_REGISTRY_OVERLAP_TOOL,
            SUBMIT_PLAN_PROCEED_TOOL,
            SUBMIT_PLAN_ROUTE_TO_HUMAN_TOOL,
            SUBMIT_PLAN_FEATURE_REQUEST_TOOL,
        )
    ]

    options = ClaudeAgentOptions(
        system_prompt=_build_system_prompt(blueprint, registry_digest, target_app),
        tools=[],
        mcp_servers={SERVER_NAME: server},
        allowed_tools=qualified_tools,
        # No permission_mode override: "bypassPermissions" refuses to run as
        # root (which this container does), and it's unnecessary here anyway —
        # tools=[] disables every built-in tool, and allowed_tools already
        # auto-approves the small, fixed set of MCP tools we define below.
        #
        # max_turns bounds the SDK's own internal turn count *within this one
        # connection* (e.g. text -> check_registry_overlap -> tool result ->
        # submit_plan_proceed is already 2 internal turns) — it is not the
        # planner's 8-turn cap, which is our own turns_used counter and spans
        # every HTTP request in this plan run. Too low a value here cuts a
        # turn off mid tool-call, before it can act on the tool's result.
        max_turns=6,
        max_budget_usd=settings.planner_max_budget_usd,
        model=settings.planner_model,
        session_id=session_id if is_first_turn else None,
        resume=None if is_first_turn else session_id,
        # SDK isolation mode: don't load this host's ~/.claude user settings,
        # project .claude/settings.json, hooks, or unrelated MCP plugins. Without
        # this, a planner session run from a Claude Code dev environment inherits
        # that environment's entire hook/skill/plugin stack — burning tens of
        # thousands of cache-creation tokens on irrelevant system-prompt injection
        # and, in one observed case, hanging on a stale messaging-socket handshake.
        setting_sources=[],
        strict_mcp_config=True,
    )

    reply_text_parts: list[str] = []
    model_usage: dict[str, Any] = {}

    async with ClaudeSDKClient(options) as client:
        await client.query(user_message)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                model_usage = message.model_usage or {}

    return PlannerTurnResult(
        reply_text="\n".join(reply_text_parts).strip(),
        outcome=captured.get("outcome"),
        model_usage=model_usage,
    )
