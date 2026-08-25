import pytest
from pydantic import ValidationError

from factory.agents.plan_schema import (
    FeatureRequestArgs,
    ProceedArgs,
    ProceedOutcome,
    RouteToHumanArgs,
)


def test_proceed_args_valid() -> None:
    args = ProceedArgs.model_validate(
        {
            "name": "Lab Sample Intake Log",
            "purpose": "Log incoming lab samples.",
            "complexity_score": 2,
            "score_justification": {"data_sources": "one CSV upload"},
            "capabilities": [{"slug": "log_sample", "description": "Log a sample."}],
        }
    )
    assert args.complexity_score == 2


def test_proceed_args_has_no_blueprint_id() -> None:
    """blueprint_id is set by the orchestrator, not solicited from the model —
    there's exactly one blueprint in this POC, so asking the model to echo its id
    back only invites hallucination (observed live: it once returned a slug that
    didn't exist)."""
    assert "blueprint_id" not in ProceedArgs.model_fields


def test_proceed_outcome_requires_blueprint_id() -> None:
    with pytest.raises(ValidationError):
        ProceedOutcome.model_validate(
            {
                "name": "x",
                "purpose": "x",
                "complexity_score": 2,
                "score_justification": {},
                "capabilities": [],
            }
        )


def test_proceed_args_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        ProceedArgs.model_validate(
            {
                "name": "x",
                "purpose": "x",
                "complexity_score": 6,
                "score_justification": {},
                "capabilities": [],
            }
        )


def test_route_to_human_args_valid() -> None:
    args = RouteToHumanArgs.model_validate(
        {
            "reason": "overlaps_existing_app",
            "owner_sub": "33333333-3333-3333-3333-333333333333",
            "owner_note": "Carol owns the existing lab sample app.",
            "message": "This overlaps an existing app — talk to Carol first.",
            "overlapping_app_slug": "lab-sample-intake-log",
        }
    )
    assert args.reason == "overlaps_existing_app"


def test_route_to_human_args_rejects_unknown_reason() -> None:
    with pytest.raises(ValidationError):
        RouteToHumanArgs.model_validate(
            {
                "reason": "not_a_real_reason",
                "owner_sub": "x",
                "owner_note": "x",
                "message": "x",
            }
        )


def test_feature_request_args_valid() -> None:
    args = FeatureRequestArgs.model_validate(
        {"target_app_slug": "lab-sample-intake-log", "description": "Add a CSV export button."}
    )
    assert args.target_app_slug == "lab-sample-intake-log"
