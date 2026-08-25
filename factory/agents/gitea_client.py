"""Pushes a generated app's local working tree to Gitea — the durable, clonable
copy humans actually interact with. Local disk (generated_apps/<slug>) stays
the working tree Build writes into and Docker builds from; Gitea is where the
repo lives once a build passes.
"""

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


def ensure_repo_exists(slug: str, settings: GiteaSettings) -> str:
    """Creates the repo if it doesn't exist yet (a pickup's second push targets
    one that already does — Gitea's own 422 on that case is the signal, not an
    error we need to avoid causing). Returns the repo's clone URL."""
    response = httpx.post(
        f"{settings.gitea_url}/api/v1/user/repos",
        headers={"Authorization": f"token {settings.gitea_token}"},
        json={"name": slug, "auto_init": False, "private": False},
        timeout=10.0,
    )
    if response.status_code not in (201, 422):
        response.raise_for_status()
    return f"{settings.gitea_url}/{settings.gitea_username}/{slug}.git"


def _with_credentials(clone_url: str, username: str, token: str) -> str:
    """Embeds a token in the clone URL for one-shot push auth. Never returned
    to callers or stored — only the plain clone_url is, so the token never
    lands in the registry or the UI."""
    return clone_url.replace("://", f"://{username}:{token}@", 1)


def push(app_dir: Path, slug: str, settings: GiteaSettings) -> str:
    """Ensures the repo exists, then pushes app_dir's current HEAD to it.
    Returns the clone URL (without the embedded token) for storage/display.

    The token is passed to `git push` as a one-shot destination URL, never
    stored as a remote — `git remote add` would write it straight into
    `.git/config` in plaintext, where it would still be sitting after this
    directory is later chowned to the host user (flagged by security review;
    an earlier version of this function did exactly that)."""
    clone_url = ensure_repo_exists(slug, settings)
    authenticated_url = _with_credentials(clone_url, settings.gitea_username, settings.gitea_token)

    try:
        subprocess.run(
            ["git", "push", authenticated_url, "HEAD:main"],
            cwd=app_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        # git's own fatal-error text can echo the failed remote URL verbatim
        # (e.g. "fatal: unable to access 'http://factory:<token>@...'") — that
        # URL carries the token, and this exception's .stderr is what
        # build_review_orchestrator surfaces to the requester as a finding on
        # failure. Scrub before it ever leaves this function, not at whatever
        # call site happens to consume it later.
        if exc.stderr:
            exc.stderr = exc.stderr.replace(authenticated_url, clone_url)
        raise

    # The stored remote (if any human or future run inspects it) points at the
    # plain, token-less URL — never the credentialed one used above.
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=app_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", clone_url],
        cwd=app_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return clone_url
