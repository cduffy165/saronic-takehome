from sqlalchemy.orm import Session

from factory.registry.queries import (
    find_apps_by_capability_slugs,
    get_app_by_slug,
    get_capabilities_for_app,
)
from factory.registry.seed import apply_seed, load_seed_file


def test_find_apps_by_capability_slugs_detects_overlap(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    matches = find_apps_by_capability_slugs(db_session, ["log_sample_intake"])

    assert [a.slug for a in matches] == ["lab-sample-intake-log"]


def test_find_apps_by_capability_slugs_no_overlap_returns_empty(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    matches = find_apps_by_capability_slugs(db_session, ["some_capability_nobody_has"])

    assert matches == []


def test_get_capabilities_for_app(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    app = get_app_by_slug(db_session, "expense-approval-tracker")
    assert app is not None

    capabilities = get_capabilities_for_app(db_session, str(app.id))

    assert {c.slug for c in capabilities} == {"submit_expense", "view_approval_status"}
