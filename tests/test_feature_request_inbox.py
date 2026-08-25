from sqlalchemy.orm import Session

from factory.registry.models import FeatureRequest
from factory.registry.queries import find_open_feature_requests_for_owner
from factory.registry.seed import apply_seed, load_seed_file

ALICE_SUB = "11111111-1111-1111-1111-111111111111"  # business owner of expense-approval-tracker
CAROL_SUB = "33333333-3333-3333-3333-333333333333"  # business owner of lab-sample-intake-log


def test_find_open_feature_requests_for_owner_returns_only_owned_app_requests(
    db_session: Session,
) -> None:
    seed_data = load_seed_file()
    apply_seed(db_session, seed_data)
    from factory.registry.queries import get_app_by_slug

    expense_app = get_app_by_slug(db_session, "expense-approval-tracker")
    lab_app = get_app_by_slug(db_session, "lab-sample-intake-log")

    db_session.add(
        FeatureRequest(app_id=expense_app.id, requester_sub="x", description="add export")
    )
    db_session.add(
        FeatureRequest(app_id=lab_app.id, requester_sub="y", description="add barcode scan")
    )
    db_session.commit()

    alice_inbox = find_open_feature_requests_for_owner(db_session, ALICE_SUB)
    carol_inbox = find_open_feature_requests_for_owner(db_session, CAROL_SUB)

    assert [fr.description for fr in alice_inbox] == ["add export"]
    assert [fr.description for fr in carol_inbox] == ["add barcode scan"]


def test_find_open_feature_requests_excludes_resolved(db_session: Session) -> None:
    apply_seed(db_session, load_seed_file())
    from factory.registry.queries import get_app_by_slug

    expense_app = get_app_by_slug(db_session, "expense-approval-tracker")
    db_session.add(
        FeatureRequest(
            app_id=expense_app.id,
            requester_sub="x",
            description="already done",
            status="resolved",
        )
    )
    db_session.commit()

    assert find_open_feature_requests_for_owner(db_session, ALICE_SUB) == []
