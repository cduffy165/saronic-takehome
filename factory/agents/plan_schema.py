"""The Plan session's three-outcome output schema.

The planner must end by calling one of three ``submit_plan_*`` tools — separate
tools rather than one tool with a discriminated-union schema, because MCP tool
input schemas must be a flat JSON object at the top level, which a ``oneOf``
union isn't. ``incomplete`` is a fourth possible result, but it's produced by
our own turn-cap enforcement, never by the model, so it has no tool at all.
"""

from typing import Literal

from pydantic import BaseModel, Field

RouteReason = Literal["overlaps_existing_app", "scope_exceeds_blueprint", "no_fitting_blueprint"]


class CapabilityDraft(BaseModel):
    slug: str
    description: str


class ProceedArgs(BaseModel):
    name: str
    purpose: str
    complexity_score: int = Field(ge=1, le=5)
    score_justification: dict[str, str]
    """Per-dimension notes, e.g. data_sources / integrations / user_roles / capability_count."""
    capabilities: list[CapabilityDraft]


class RouteToHumanArgs(BaseModel):
    reason: RouteReason
    owner_sub: str
    """Keycloak subject of the named owner the requester should talk to."""
    owner_note: str
    """Human-readable context, e.g. the owner's name/role and why they're named."""
    message: str
    """The recommendation shown to the requester. Recommends a conversation; never a refusal."""
    overlapping_app_slug: str | None = None


class FeatureRequestArgs(BaseModel):
    target_app_slug: str
    description: str


class ProceedOutcome(ProceedArgs):
    outcome: Literal["proceed"] = "proceed"
    blueprint_id: str
    """Set by the orchestrator, not the model — there is exactly one blueprint in
    this POC, so asking the model to echo its id back just invites hallucination."""


class RouteToHumanOutcome(RouteToHumanArgs):
    outcome: Literal["route_to_human"] = "route_to_human"


class FeatureRequestOutcome(FeatureRequestArgs):
    outcome: Literal["feature_request"] = "feature_request"


class IncompleteOutcome(BaseModel):
    """Produced by the orchestrator, not the model, when the turn cap is hit."""

    outcome: Literal["incomplete"] = "incomplete"
    turns_used: int
    still_needed: str
    """What the planner still needed to know, for a human to pick up."""


PlanOutcome = ProceedOutcome | RouteToHumanOutcome | FeatureRequestOutcome | IncompleteOutcome

SUBMIT_PLAN_PROCEED_TOOL = "submit_plan_proceed"
SUBMIT_PLAN_ROUTE_TO_HUMAN_TOOL = "submit_plan_route_to_human"
SUBMIT_PLAN_FEATURE_REQUEST_TOOL = "submit_plan_feature_request"
CHECK_REGISTRY_OVERLAP_TOOL = "check_registry_overlap"
