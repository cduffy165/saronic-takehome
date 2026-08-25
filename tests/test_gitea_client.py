from factory.agents.gitea_client import _with_credentials


def test_with_credentials_embeds_username_and_token() -> None:
    url = _with_credentials("http://gitea:3000/factory/my-app.git", "factory", "abc123")

    assert url == "http://factory:abc123@gitea:3000/factory/my-app.git"


def test_with_credentials_does_not_duplicate_scheme_separator() -> None:
    url = _with_credentials("http://gitea:3000/factory/my-app.git", "factory", "abc123")

    assert url.count("://") == 1
    assert url.startswith("http://factory:abc123@")
