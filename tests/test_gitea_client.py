from unittest.mock import patch

import pytest

from factory.agents.gitea_client import GiteaSettings, _with_credentials, push


def test_with_credentials_embeds_username_and_token() -> None:
    url = _with_credentials("http://gitea:3000/factory/my-app.git", "factory", "abc123")

    assert url == "http://factory:abc123@gitea:3000/factory/my-app.git"


def test_with_credentials_does_not_duplicate_scheme_separator() -> None:
    url = _with_credentials("http://gitea:3000/factory/my-app.git", "factory", "abc123")

    assert url.count("://") == 1
    assert url.startswith("http://factory:abc123@")


def test_push_scrubs_token_from_failed_push_error(tmp_path, monkeypatch) -> None:
    """Real git/libcurl already redacts credentials from its own error text in
    the failure modes tested live against a real Gitea instance, but this
    scrub is defense-in-depth against any version/transport that doesn't —
    verified directly here without relying on a particular git build's
    behavior."""
    import subprocess

    settings = GiteaSettings(
        gitea_url="http://gitea:3000", gitea_username="factory", gitea_token="supersecrettoken"
    )
    authenticated_url = "http://factory:supersecrettoken@gitea:3000/factory/my-app.git"

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(
                1, cmd, stderr=f"fatal: unable to access '{authenticated_url}/': error"
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with (
        patch(
            "factory.agents.gitea_client.ensure_repo_exists",
            return_value="http://gitea:3000/factory/my-app.git",
        ),
        pytest.raises(subprocess.CalledProcessError) as exc_info,
    ):
        push(tmp_path, "my-app", settings)

    assert "supersecrettoken" not in exc_info.value.stderr
    assert "http://gitea:3000/factory/my-app.git" in exc_info.value.stderr
