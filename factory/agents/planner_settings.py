"""Runtime configuration for the Plan session."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class PlannerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    planner_model: str = "claude-sonnet-4-5"
    planner_max_turns: int = 8
    planner_max_budget_usd: float = 2.0


def get_planner_settings() -> PlannerSettings:
    return PlannerSettings()
