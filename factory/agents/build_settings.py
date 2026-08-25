"""Runtime configuration for the Build and Review sessions."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BuildSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    build_model: str = "claude-sonnet-4-5"
    # Generous: every file write is its own internal SDK turn.
    build_max_turns: int = 30
    build_max_budget_usd: float = 1.5

    review_model: str = "claude-sonnet-4-5"
    review_max_turns: int = 6
    review_max_budget_usd: float = 0.5

    # 1 retry: a run gets two attempts total before it's reported as failed.
    max_build_review_attempts: int = 2

    # The api container runs as root (needed for docker socket access), so
    # generated_apps/<slug> is written root-owned unless chowned back to the host
    # dev's uid/gid — otherwise "code lands somewhere humans can edit it" fails
    # silently for any non-root host user. Override to match your host user if
    # it isn't 1000 (`id -u` / `id -g`).
    host_uid: int = 1000
    host_gid: int = 1000


def get_build_settings() -> BuildSettings:
    return BuildSettings()
