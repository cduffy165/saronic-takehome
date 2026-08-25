import base64
from unittest.mock import patch

import pytest

from factory.agents.gitea_client import GiteaSettings, _basic_auth_header, push


def test_basic_auth_header_encodes_username_and_token() -> None:
    header = _basic_auth_header("factory", "abc123")

    assert header == f"Authorization: Basic {base64.b64encode(b'factory:abc123').decode()}"


def test_push_never_embeds_token_in_the_push_destination(tmp_path, monkeypatch) -> None:
    """The token must reach git only via GIT_CONFIG_VALUE_0 in the subprocess
    environment, never as part of the destination URL passed on argv — an
    embedded-in-URL token can be echoed back verbatim in git's own
    fatal-error text on a failed push, as an earlier version of this
    function did."""
    import subprocess

    settings = GiteaSettings(
        gitea_url="http://gitea:3000", gitea_username="factory", gitea_token="supersecrettoken"
    )
    seen_cmds = []

    def fake_run(cmd, **kwargs):
        seen_cmds.append((cmd, kwargs.get("env")))
        if cmd[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(
                1,
                cmd,
                stderr="fatal: unable to access 'http://gitea:3000/factory/my-app.git/': error",
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
    push_cmd, push_env = seen_cmds[0]
    assert push_cmd == ["git", "push", "http://gitea:3000/factory/my-app.git", "HEAD:main"]
    assert "supersecrettoken" not in " ".join(push_cmd)
    assert push_env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    expected_creds = base64.b64encode(b"factory:supersecrettoken").decode()
    assert push_env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected_creds}"
