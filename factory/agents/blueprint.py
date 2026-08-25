"""Blueprint loading and scope-rating comparison.

Blueprints are architectural patterns supplied by IT (not app templates). There is
one for this POC. A request that scores above ``max_score`` on the blueprint's
scale routes to a human instead of building — this comparison is a plain integer
check, not model judgment, so it's deterministic and testable.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel

BLUEPRINTS_DIR = Path(__file__).resolve().parents[2] / "blueprints"


class ScaleLevel(BaseModel):
    label: str
    examples: list[str]


class Blueprint(BaseModel):
    id: str
    name: str
    description: str
    max_score: int
    scale: dict[int, ScaleLevel]


def load_blueprint(blueprint_id: str, blueprints_dir: Path = BLUEPRINTS_DIR) -> Blueprint:
    path = blueprints_dir / f"{blueprint_id}.yaml"
    data = yaml.safe_load(path.read_text())
    return Blueprint.model_validate(data)


def exceeds_scope(blueprint: Blueprint, complexity_score: int) -> bool:
    return complexity_score > blueprint.max_score


def render_scale_for_prompt(blueprint: Blueprint) -> str:
    """A human-readable rendering of the blueprint's scale, for the planner's system prompt."""
    lines = [
        f"Blueprint: {blueprint.name} (max_score={blueprint.max_score})",
        blueprint.description,
    ]
    for level in sorted(blueprint.scale):
        entry = blueprint.scale[level]
        examples = "; ".join(entry.examples)
        lines.append(f"  {level}: {entry.label} — e.g. {examples}")
    return "\n".join(lines)
