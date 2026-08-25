"""Pushes a generated app's local working tree to Gitea — the durable, clonable
copy humans actually interact with. Local disk (generated_apps/<slug>) stays
the working tree Build writes into and Docker builds from; Gitea is where the
repo lives once a build passes.
"""

import base64
import os
import subprocess
from pathlib import Path

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class GiteaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gitea_url: str = "http://gitea:3000"
    gitea_username: str = "factory"
    gitea_token: str = ""


def get_gitea_settings() -> GiteaSettings:
    return GiteaSettings()


def _auth_headers(settings: GiteaSettings) -> dict[str, str]:
    return {"Authorization": f"token {settings.gitea_token}"}


def ensure_repo_exists(slug: str, settings: GiteaSettings) -> str:
    """Creates the repo if it doesn't exist yet (a pickup's second push targets
    one that already does — Gitea's own 422 on that case is the signal, not an
    error we need to avoid causing). Returns the repo's clone URL."""
    response = httpx.post(
        f"{settings.gitea_url}/api/v1/user/repos",
        headers=_auth_headers(settings),
        json={"name": slug, "auto_init": False, "private": False},
        timeout=10.0,
    )
    if response.status_code not in (201, 422):
        response.raise_for_status()
    return f"{settings.gitea_url}/{settings.gitea_username}/{slug}.git"


def delete_repo(slug: str, settings: GiteaSettings) -> None:
    """Removes a repo — eval cleanup only; the running factory never deletes one."""
    httpx.delete(
        f"{settings.gitea_url}/api/v1/repos/{settings.gitea_username}/{slug}",
        headers=_auth_headers(settings),
        timeout=10.0,
    )


def _basic_auth_header(username: str, token: str) -> str:
    creds = base64.b64encode(f"{username}:{token}".encode()).decode()
    return f"Authorization: Basic {creds}"


def push(app_dir: Path, slug: str, settings: GiteaSettings) -> str:
    """Ensures the repo exists, then pushes app_dir's current HEAD to it.
    Returns the clone URL for storage/display.

    The token is sent as a `git -c http.extraHeader` value passed through the
    environment rather than embedded in the destination URL or any argv value
    — `git remote add <url-with-token>` would write it straight into
    `.git/config` in plaintext, where it would still be sitting after this
    directory is later chowned to the host user (flagged by security review;
    an earlier version of this function did exactly that), and even a
    one-shot credentialed URL risks being echoed back verbatim in git's own
    fatal-error text on a failed push."""
    clone_url = ensure_repo_exists(slug, settings)
    auth_header = _basic_auth_header(settings.gitea_username, settings.gitea_token)
    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": auth_header,
    }
    subprocess.run(
        ["git", "push", clone_url, "HEAD:main"],
        cwd=app_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    # Point the stored remote at the same (token-less) URL just pushed to.
    # `remote add` fails if a remote from an earlier pickup push already
    # exists, in which case `set-url` is the right follow-up.
    added = subprocess.run(
        ["git", "remote", "add", "origin", clone_url],
        cwd=app_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        subprocess.run(
            ["git", "remote", "set-url", "origin", clone_url],
            cwd=app_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    return clone_url
