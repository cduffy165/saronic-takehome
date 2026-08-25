from sqlalchemy.orm import Session

from factory.agents.plan_session import _render_registry_digest
from factory.registry.seed import apply_seed, load_seed_file


def test_registry_digest_empty_registry(db_session: Session) -> None:
    digest = _render_registry_digest(db_session)

    assert "no active apps" in digest.lower()


def test_registry_digest_includes_capabilities_and_owners(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    digest = _render_registry_digest(db_session)

    assert "lab-sample-intake-log" in digest
    assert "log_sample_intake" in digest
    assert "33333333-3333-3333-3333-333333333333" in digest  # carol, business owner
    assert "44444444-4444-4444-4444-444444444444" in digest  # dave, technical owner
