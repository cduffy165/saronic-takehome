"""Grades a generated app's security and quality.

Generated apps are deliberately tiny (blueprint max_score=2, a handful of
files), so the whole tree is inlined into the prompt rather than given via
filesystem tools — cheaper, no tool round-trips, and it means Review has zero
built-in tools at all (it cannot write, execute, or even read arbitrary paths).
"""

from dataclasses import dataclass, field
from pathlib import Path
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

from factory.agents.build_review_schema import SUBMIT_REVIEW_TOOL, ReviewResult
from factory.agents.build_settings import get_build_settings

SERVER_NAME = "factory_reviewer"
_INLINE_SUFFIXES = {".py", ".txt", ".toml", ".cfg", ".ini", ".md", ".yaml", ".yml"}
_SKIP_DIRS = {".git", "__pycache__", ".venv"}


@dataclass
class ReviewTurnResult:
    result: ReviewResult | None
    model_usage: dict[str, Any] = field(default_factory=dict)


def _render_file_tree(app_dir: Path) -> str:
    blocks = []
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(app_dir)
        if path.suffix not in _INLINE_SUFFIXES:
            blocks.append(f"### {rel}\n(binary or non-text file, not inlined)")
            continue
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            content = "(could not read file)"
        blocks.append(f"### {rel}\n```\n{content}\n```")
    return "\n\n".join(blocks) if blocks else "(no files found)"


def _build_system_prompt() -> str:
    return f"""You are the Review stage of an internal app factory. You are given the
complete file tree of a small, freshly generated internal app. Grade it for
security and quality, then finish by calling {SUBMIT_REVIEW_TOOL} exactly once.

Focus areas:
- Secrets and credentials: any real-looking API key, password, or token;
  placeholders and environment-variable reads with safe local defaults are fine.
- Injection: unsanitized input passed to a query, shell command, or eval.
- Missing input validation on anything that writes state.
- Whether the app actually implements the capabilities it was asked for.

Set verdict to "fail" if there are any high-severity findings, "pass" otherwise.
Be concrete — each finding should name the file and the specific issue."""


def _make_review_tool(captured: dict[str, Any]):
    @tool(SUBMIT_REVIEW_TOOL, "Finalize the review.", ReviewResult.model_json_schema())
    async def submit_review(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = ReviewResult.model_validate(args)
        except ValidationError as exc:
            return {
                "content": [{"type": "text", "text": f"Invalid review payload: {exc}"}],
                "is_error": True,
            }
        captured["result"] = result
        return {"content": [{"type": "text", "text": "Review recorded."}]}

    return create_sdk_mcp_server(name=SERVER_NAME, tools=[submit_review])


async def run_review_turn(*, app_dir: Path) -> ReviewTurnResult:
    settings = get_build_settings()
    captured: dict[str, Any] = {}
    server = _make_review_tool(captured)

    options = ClaudeAgentOptions(
        system_prompt=_build_system_prompt(),
        tools=[],
        mcp_servers={SERVER_NAME: server},
        allowed_tools=[f"mcp__{SERVER_NAME}__{SUBMIT_REVIEW_TOOL}"],
        max_turns=settings.review_max_turns,
        max_budget_usd=settings.review_max_budget_usd,
        model=settings.review_model,
        setting_sources=[],
        strict_mcp_config=True,
    )

    reply_text_parts: list[str] = []
    model_usage: dict[str, Any] = {}

    async with ClaudeSDKClient(options) as client:
        await client.query(f"Review this app:\n\n{_render_file_tree(app_dir)}")
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                model_usage = message.model_usage or {}

    return ReviewTurnResult(result=captured.get("result"), model_usage=model_usage)
