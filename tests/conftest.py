"""Shared fixtures for registry tests.

Uses testcontainers to run a real Postgres for the duration of the test session,
so registry tests exercise actual jsonb/SQL behavior without requiring
``docker compose up`` to already be running.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from factory.registry.models import Base

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def db_engine(postgres_url: str) -> Iterator[Engine]:
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session against a truncated (not just rolled back) database.

    Code under test (the seed loader) commits internally, so a rollback-only
    wrapper wouldn't isolate tests from each other. Truncating between tests
    does.
    """
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = session_factory()

    yield session

    session.close()
    table_names = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))
    with db_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))
