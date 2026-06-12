from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTERNHUNTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: Path = Path("internhunter.db")
    http_concurrency: int = 16
    per_host_concurrency: int = 4
    default_user_agent: str = "InternHunter/0.1 (+https://github.com/internhunter)"
    request_timeout: float = 30.0
    cache_dir: Path = Path(".cache")
    retry_max_attempts: int = 4
    embed_model: str = "all-MiniLM-L6-v2"
    embed_device: str = "cpu"
    profile_path: Path = Path("internhunter/config/profile.yaml")
    browser_engine: str = "playwright"
    browser_headless: bool = True
    enable_browser: bool = False
    llm_model: str = "claude-opus-4-8"
    llm_backend: str = "auto"
    llm_max_tokens: int = 1024
    notify_min_fit: float = 0.6
    auth_user: str = ""
    auth_pass: str = ""
    dashboard_limit: int = 2000
    discord_webhook_url: str = ""
    ntfy_topic_url: str = ""
    feed_path: Path = Path("internhunter.feed.xml")
    searxng_url: str = ""


def get_settings() -> Settings:
    return Settings()
