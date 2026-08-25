from dataclasses import dataclass, field

from factory.agents.plan_orchestrator import _validated_owner_sub


@dataclass
class _FakeOwner:
    keycloak_sub: str
    role: str


@dataclass
class _FakeApp:
    owners: list[_FakeOwner] = field(default_factory=list)


def test_validated_owner_sub_accepts_real_owner() -> None:
    app = _FakeApp(
        owners=[_FakeOwner("carol-sub", "business"), _FakeOwner("dave-sub", "technical")]
    )

    assert _validated_owner_sub(app, "dave-sub") == "dave-sub"


def test_validated_owner_sub_substitutes_business_owner_for_fabricated_sub() -> None:
    app = _FakeApp(
        owners=[_FakeOwner("carol-sub", "business"), _FakeOwner("dave-sub", "technical")]
    )

    assert _validated_owner_sub(app, "made-up-sub") == "carol-sub"


def test_validated_owner_sub_falls_back_to_first_owner_when_no_business_owner() -> None:
    app = _FakeApp(owners=[_FakeOwner("dave-sub", "technical")])

    assert _validated_owner_sub(app, "made-up-sub") == "dave-sub"


def test_validated_owner_sub_returns_input_when_app_has_no_owners() -> None:
    app = _FakeApp(owners=[])

    assert _validated_owner_sub(app, "made-up-sub") == "made-up-sub"
