"""Registry read queries shared by the planner, the UI, and evals.

These are plain SQL over rows (not jsonb path expressions) so duplicate detection
and capability lookups are deterministic and testable against a fixed registry state.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from factory.registry.models import App, Capability


def find_apps_by_capability_slugs(session: Session, slugs: list[str]) -> list[App]:
    """Apps that already declare any of the given capability slugs.

    Used by the planner to detect overlap with an existing app before deciding
    between ``proceed`` and ``route_to_human``.
    """
    if not slugs:
        return []
    stmt = (
        select(App)
        .join(Capability)
        .where(Capability.slug.in_(slugs), App.status == "active")
        .distinct()
    )
    return list(session.scalars(stmt))


def get_capabilities_for_app(session: Session, app_id: str) -> list[Capability]:
    stmt = select(Capability).where(Capability.app_id == app_id)
    return list(session.scalars(stmt))


def get_app_by_slug(session: Session, slug: str) -> App | None:
    stmt = select(App).where(App.slug == slug)
    return session.scalars(stmt).first()


def list_apps(session: Session) -> list[App]:
    stmt = select(App).order_by(App.name)
    return list(session.scalars(stmt))
