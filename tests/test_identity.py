from factory.registry.identity import display_name

ALICE_SUB = "11111111-1111-1111-1111-111111111111"


def test_display_name_resolves_a_known_fixture_user() -> None:
    assert display_name(ALICE_SUB) == "Alice Anderson"


def test_display_name_falls_back_to_a_shortened_sub_for_unknown_values() -> None:
    unknown_sub = "99999999-9999-9999-9999-999999999999"

    assert display_name(unknown_sub) == "99999999"


def test_display_name_never_raises_on_empty_input() -> None:
    assert display_name("") == "unknown"
