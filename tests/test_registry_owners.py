from sqlalchemy.orm import Session

from factory.registry.queries import find_apps_owned_by
from factory.registry.seed import apply_seed, load_seed_file

ALICE_SUB = "11111111-1111-1111-1111-111111111111"
DAVE_SUB = "44444444-4444-4444-4444-444444444444"


def test_find_apps_owned_by_returns_only_that_users_apps(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    assert [a.slug for a in find_apps_owned_by(db_session, ALICE_SUB)] == [
        "expense-approval-tracker"
    ]
    assert [a.slug for a in find_apps_owned_by(db_session, DAVE_SUB)] == ["lab-sample-intake-log"]


def test_find_apps_owned_by_unknown_sub_returns_empty(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())

    assert find_apps_owned_by(db_session, "nobody") == []
