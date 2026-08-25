"""Stands in for the human on the other side of an interactive Plan session.

Plan is multi-turn and asks clarifying questions, so an eval needs deterministic
input to drive it. A scripted requester answers by matching keywords in the
planner's latest question against a canned answer table, falling back to a
default reply that nudges the planner to finalize.
"""

from dataclasses import dataclass


@dataclass
class ScriptedRequester:
    answers: dict[str, str]
    """Keyword -> canned reply. Matched case-insensitively, first match wins."""
    fallback_reply: str

    def reply_to(self, planner_message: str) -> str:
        lowered = planner_message.lower()
        for keyword, reply in self.answers.items():
            if keyword.lower() in lowered:
                return reply
        return self.fallback_reply
