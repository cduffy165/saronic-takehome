"""Engine and session factory for the registry database."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from factory.registry.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session scoped to one request."""
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
