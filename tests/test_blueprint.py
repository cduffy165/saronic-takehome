from factory.agents.blueprint import exceeds_scope, load_blueprint, render_scale_for_prompt


def test_load_blueprint_streamlit_small() -> None:
    blueprint = load_blueprint("streamlit-small")

    assert blueprint.id == "streamlit-small"
    assert blueprint.max_score == 2
    assert set(blueprint.scale) == {1, 2, 3, 4, 5}


def test_exceeds_scope() -> None:
    blueprint = load_blueprint("streamlit-small")

    assert exceeds_scope(blueprint, 1) is False
    assert exceeds_scope(blueprint, 2) is False
    assert exceeds_scope(blueprint, 3) is True


def test_render_scale_for_prompt_includes_examples() -> None:
    blueprint = load_blueprint("streamlit-small")

    rendered = render_scale_for_prompt(blueprint)

    assert "max_score=2" in rendered
    assert "log lab samples and list them by intake date" in rendered
