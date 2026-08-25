"""Loads the declarative registry seed file into the database.

Idempotent by design: re-running against an already-seeded database updates rows
in place (keyed by slug) rather than duplicating them, so ``make seed`` is safe
to run repeatedly in development and in eval setup.
"""

import argparse
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from factory.registry.db import get_session_factory
from factory.registry.models import App, AppOwner, Capability

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "seeds" / "registry.yaml"


def load_seed_file(path: Path = DEFAULT_SEED_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def apply_seed(session: Session, seed: dict[str, Any]) -> None:
    for app_data in seed.get("apps", []):
        _upsert_app(session, app_data)
    session.commit()


def _upsert_app(session: Session, app_data: dict[str, Any]) -> None:
    app = session.query(App).filter_by(slug=app_data["slug"]).one_or_none()
    if app is None:
        app = App(slug=app_data["slug"], manifest={})
        session.add(app)

    app.name = app_data["name"]
    app.purpose = app_data["purpose"]
    app.blueprint_id = app_data["blueprint_id"]
    app.complexity_score = app_data["complexity_score"]
    session.flush()  # assigns app.id for new rows

    _upsert_owners(session, app, app_data.get("owners", []))
    _upsert_capabilities(session, app, app_data.get("capabilities", []))


def _upsert_owners(session: Session, app: App, owners_data: list[dict[str, Any]]) -> None:
    existing = {o.keycloak_sub: o for o in app.owners}
    for owner_data in owners_data:
        owner = existing.get(owner_data["keycloak_sub"])
        if owner is None:
            session.add(
                AppOwner(
                    app_id=app.id,
                    keycloak_sub=owner_data["keycloak_sub"],
                    role=owner_data["role"],
                )
            )
        else:
            owner.role = owner_data["role"]


def _upsert_capabilities(
    session: Session, app: App, capabilities_data: list[dict[str, Any]]
) -> None:
    existing = {c.slug: c for c in app.capabilities}
    for cap_data in capabilities_data:
        capability = existing.get(cap_data["slug"])
        if capability is None:
            session.add(
                Capability(
                    app_id=app.id,
                    slug=cap_data["slug"],
                    description=cap_data["description"],
                )
            )
        else:
            capability.description = cap_data["description"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the registry seed file.")
    parser.add_argument("--path", type=Path, default=DEFAULT_SEED_PATH)
    args = parser.parse_args()

    seed = load_seed_file(args.path)
    session_factory = get_session_factory()
    with session_factory() as session:
        apply_seed(session, seed)


if __name__ == "__main__":
    main()
