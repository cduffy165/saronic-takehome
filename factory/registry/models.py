"""SQLAlchemy models for the registry.

The manifest jsonb column on ``App`` is the raw planning artifact. ``capabilities``
exists as its own table (not just a jsonb array) so duplicate detection and scope
comparisons are plain SQL rather than model judgment over prose.
"""

import datetime
import uuid
from typing import Any

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class App(Base):
    __tablename__ = "apps"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    purpose: Mapped[str]
    blueprint_id: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    complexity_score: Mapped[int]
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    repo_path: Mapped[str | None] = mapped_column(default=None)
    container_port: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    owners: Mapped[list["AppOwner"]] = relationship(
        back_populates="app", cascade="all, delete-orphan"
    )
    capabilities: Mapped[list["Capability"]] = relationship(
        back_populates="app", cascade="all, delete-orphan"
    )
    feature_requests: Mapped[list["FeatureRequest"]] = relationship(
        back_populates="app", cascade="all, delete-orphan"
    )
    runs: Mapped[list["Run"]] = relationship(back_populates="app", cascade="all, delete-orphan")


class AppOwner(Base):
    __tablename__ = "app_owners"

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True
    )
    keycloak_sub: Mapped[str] = mapped_column(primary_key=True)
    role: Mapped[str]
    """One of ``business`` or ``technical``."""

    app: Mapped[App] = relationship(back_populates="owners")


class Capability(Base):
    __tablename__ = "capabilities"

    id: Mapped[uuid.UUID] = _uuid_pk()
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    slug: Mapped[str]
    description: Mapped[str]
    added_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    app: Mapped[App] = relationship(back_populates="capabilities")


class FeatureRequest(Base):
    __tablename__ = "feature_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    requester_sub: Mapped[str]
    description: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    """One of ``open``, ``picked_up``, ``resolved``."""
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    app: Mapped[App] = relationship(back_populates="feature_requests")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    app_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("apps.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str]
    """One of ``plan``, ``build_review``."""
    outcome: Mapped[str | None] = mapped_column(default=None)
    """For ``plan`` runs: ``proceed`` | ``route_to_human`` | ``feature_request`` | ``incomplete``."""
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    turns_used: Mapped[int] = mapped_column(default=0)
    """Planner turn count, enforced against the cap independently of the SDK's own
    per-connection ``max_turns`` — each HTTP request resumes the session as a new
    SDK client, so the cap has to be tracked here to hold across requests."""
    plan_approved_at: Mapped[datetime.datetime | None] = mapped_column(default=None)
    """Gate 1: set when a human approves a ``proceed`` plan, before Build spend."""
    requester_sub: Mapped[str | None] = mapped_column(default=None)
    plan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), default=None
    )
    """For ``build_review`` runs: the ``plan`` run whose approved outcome it builds."""
    repo_path: Mapped[str | None] = mapped_column(default=None)
    """For ``build_review`` runs: the generated app's directory, once Build succeeds."""
    container_port: Mapped[int | None] = mapped_column(default=None)
    """For ``build_review`` runs: the allocated host port, once the container is running."""
    build_approved_at: Mapped[datetime.datetime | None] = mapped_column(default=None)
    """Gate 2: set when a human approves a successful build for registration."""
    feature_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feature_requests.id", ondelete="SET NULL"), default=None
    )
    """For ``plan`` runs started via feature-request pickup (M7): which request
    this run is fulfilling — an app can have more than one open request."""
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    app: Mapped[App | None] = relationship(back_populates="runs", foreign_keys=[app_id])
    cost_events: Mapped[list["CostEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class CostEvent(Base):
    __tablename__ = "cost_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    app_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("apps.id", ondelete="SET NULL"), default=None
    )
    stage: Mapped[str]
    """One of ``plan``, ``build``, ``review``."""
    model: Mapped[str]
    input_tokens: Mapped[int]
    cached_tokens: Mapped[int]
    output_tokens: Mapped[int]
    usd: Mapped[float]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="cost_events")
