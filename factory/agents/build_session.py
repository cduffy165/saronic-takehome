"""Writes a generated app's source tree.

The Build agent's only capability is writing files inside its own app
directory — no Bash, no network, no access outside that directory. Bringing
the container up is deterministic code (factory/agents/container_runtime.py),
not agent-driven: an LLM never runs arbitrary shell commands in this pipeline.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
)

from factory.agents.build_settings import get_build_settings


@dataclass
class BuildTurnResult:
    model_usage: dict[str, Any] = field(default_factory=dict)


def _make_path_guard(app_dir: Path):
    resolved_root = app_dir.resolve()

    async def guard(tool_name: str, tool_input: dict[str, Any], _context: Any):
        if tool_name not in ("Write", "Edit"):
            return PermissionResultAllow()

        raw_path = tool_input.get("file_path", "")
        candidate = Path(raw_path)
        target = candidate if candidate.is_absolute() else app_dir / candidate
        try:
            resolved = target.resolve()
            resolved.relative_to(resolved_root)
        except ValueError:
            return PermissionResultDeny(
                message=(
                    f"Refusing to write outside the app directory: {raw_path!r} "
                    f"resolves outside {resolved_root}."
                )
            )
        return PermissionResultAllow()

    return guard


def _build_prompt(plan: dict[str, Any], feedback: str | None, *, is_pickup: bool) -> str:
    capabilities = "\n".join(f"- {c['slug']}: {c['description']}" for c in plan["capabilities"])
    feedback_block = (
        f"\n\nA previous attempt failed review with these findings — fix them:\n{feedback}\n"
        if feedback
        else ""
    )

    if is_pickup:
        return f"""The current directory already contains a small Streamlit app's source —
read its files first. Add this new capability without removing or breaking
any existing functionality:

{capabilities}

Change note: {plan["purpose"]}

Keep the same conventions and state approach already used in the app (in-memory
or local SQLite — no external services, no real credentials, only placeholder
values if new config is needed). Update README.md to mention the addition.
Update requirements.txt only if a new dependency is genuinely needed.{feedback_block}"""

    return f"""Write a small internal Streamlit app in the current directory implementing:

Name: {plan["name"]}
Purpose: {plan["purpose"]}
Capabilities:
{capabilities}

Requirements:
- app.py: the Streamlit app. Use only in-memory or local SQLite state — no
  external services, no real credentials of any kind, only placeholder values
  if any config is needed (e.g. read from environment variables with safe
  local defaults, never hardcode a real-looking secret).
- Dockerfile: runs app.py with Streamlit, based on python:3.13-slim.
- README.md: what the app does and how to run it — you are writing this app's
  own documentation; nothing else produces it.
- requirements.txt: pinned dependencies (at minimum streamlit).

Keep it small and working — this is a deliberately minimal proof-of-concept app,
not a production system.{feedback_block}"""


async def run_build_turn(
    *, app_dir: Path, plan: dict[str, Any], feedback: str | None = None, is_pickup: bool = False
) -> BuildTurnResult:
    settings = get_build_settings()

    options = ClaudeAgentOptions(
        cwd=str(app_dir),
        tools=["Write", "Edit", "Read"],
        allowed_tools=[],  # deliberately empty: nothing is pre-shadowed, so every
        # Write/Edit call falls through to can_use_tool for the path-containment
        # check below, instead of being auto-approved before it runs.
        can_use_tool=_make_path_guard(app_dir),
        max_turns=settings.build_max_turns,
        max_budget_usd=settings.build_max_budget_usd,
        model=settings.build_model,
        setting_sources=[],
        strict_mcp_config=True,
    )

    model_usage: dict[str, Any] = {}
    async with ClaudeSDKClient(options) as client:
        await client.query(_build_prompt(plan, feedback, is_pickup=is_pickup))
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                model_usage = message.model_usage or {}

    return BuildTurnResult(model_usage=model_usage)
