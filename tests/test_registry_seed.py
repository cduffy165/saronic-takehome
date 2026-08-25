from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factory.registry.models import App, AppOwner, Capability
from factory.registry.queries import list_apps
from factory.registry.seed import apply_seed, load_seed_file


def test_seed_loads_expected_apps(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    apps = list_apps(db_session)
    assert {a.slug for a in apps} == {"expense-approval-tracker", "lab-sample-intake-log"}


def test_seed_is_idempotent(db_session: Session) -> None:
    seed = load_seed_file()

    apply_seed(db_session, seed)
    apply_seed(db_session, seed)

    assert db_session.scalar(select(func.count()).select_from(App)) == 2
    assert db_session.scalar(select(func.count()).select_from(Capability)) == 4
    assert db_session.scalar(select(func.count()).select_from(AppOwner)) == 4


def test_seed_update_is_reflected_not_duplicated(db_session: Session) -> None:
    seed = load_seed_file()
    apply_seed(db_session, seed)

    seed["apps"][0]["name"] = "Renamed Expense Tracker"
    apply_seed(db_session, seed)

    assert db_session.scalar(select(func.count()).select_from(App)) == 2
    app = db_session.scalar(select(App).where(App.slug == seed["apps"][0]["slug"]))
    assert app is not None
    assert app.name == "Renamed Expense Tracker"
