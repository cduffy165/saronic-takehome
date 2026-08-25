from dataclasses import dataclass, field

from factory.agents.plan_orchestrator import _is_keycloak_sub, _validated_owner_sub

CAROL_SUB = "33333333-3333-3333-3333-333333333333"
DAVE_SUB = "44444444-4444-4444-4444-444444444444"


@dataclass
class _FakeOwner:
    keycloak_sub: str
    role: str


@dataclass
class _FakeApp:
    owners: list[_FakeOwner] = field(default_factory=list)


def test_is_keycloak_sub_accepts_uuid() -> None:
    assert _is_keycloak_sub(CAROL_SUB) is True


def test_is_keycloak_sub_rejects_plain_username() -> None:
    assert _is_keycloak_sub("carol") is False


def test_validated_owner_sub_accepts_real_owner() -> None:
    app = _FakeApp(owners=[_FakeOwner(CAROL_SUB, "business"), _FakeOwner(DAVE_SUB, "technical")])

    assert _validated_owner_sub(app, DAVE_SUB) == DAVE_SUB


def test_validated_owner_sub_substitutes_business_owner_for_fabricated_sub() -> None:
    app = _FakeApp(owners=[_FakeOwner(CAROL_SUB, "business"), _FakeOwner(DAVE_SUB, "technical")])

    assert _validated_owner_sub(app, "made-up-sub") == CAROL_SUB


def test_validated_owner_sub_falls_back_to_first_owner_when_no_business_owner() -> None:
    app = _FakeApp(owners=[_FakeOwner(DAVE_SUB, "technical")])

    assert _validated_owner_sub(app, "made-up-sub") == DAVE_SUB


def test_validated_owner_sub_returns_input_when_app_has_no_owners() -> None:
    app = _FakeApp(owners=[])

    assert _validated_owner_sub(app, "made-up-sub") == "made-up-sub"


def test_validated_owner_sub_rejects_stale_non_uuid_row_even_when_it_matches() -> None:
    """Regression test: a live eval run hit exactly this — app_owners had a
    leftover non-UUID row ("carol", written before requester identity was
    backed by a verified Keycloak subject) alongside the real UUID owner.
    The model echoed "carol" back, and the old check ("is it in app.owners at
    all?") accepted it because the stale row made it technically present.
    Real owners are always UUIDs; this must fall back to a real one instead."""
    app = _FakeApp(owners=[_FakeOwner("carol", "business"), _FakeOwner(DAVE_SUB, "technical")])

    assert _validated_owner_sub(app, "carol") == DAVE_SUB


def test_validated_owner_sub_prefers_business_owner_even_if_stale_rows_exist() -> None:
    app = _FakeApp(
        owners=[
            _FakeOwner("carol", "business"),
            _FakeOwner(CAROL_SUB, "business"),
            _FakeOwner(DAVE_SUB, "technical"),
        ]
    )

    assert _validated_owner_sub(app, "made-up-sub") == CAROL_SUB
