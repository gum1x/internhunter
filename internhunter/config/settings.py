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
    # Hard cap on a single response body. Bounds memory, the on-disk cache, and the
    # downstream parsers/regexes against hostile oversized responses (~25 MB default).
    max_response_bytes: int = 25_000_000
    cache_dir: Path = Path(".cache")
    retry_max_attempts: int = 4
    embed_model: str = "all-MiniLM-L6-v2"
    embed_device: str = "cpu"
    profile_path: Path = Path("internhunter/config/profile.yaml")
    # Résumé feeds the LLM rating. Default stem -> looks for resume.md/.txt/.pdf in cwd.
    resume_path: Path = Path("resume")
    browser_engine: str = "playwright"
    browser_headless: bool = True
    enable_browser: bool = False
    llm_model: str = "claude-opus-4-8"
    llm_backend: str = "auto"
    claude_bin: str = "claude"  # path to the `claude` CLI for the browser-login backend
    llm_max_tokens: int = 1024
    notify_min_fit: float = 0.6
    auth_user: str = ""
    auth_pass: str = ""
    dashboard_limit: int = 2000
    dashboard_page_size: int = 200  # rows per page in the dashboard table
    discord_webhook_url: str = ""
    ntfy_topic_url: str = ""
    feed_path: Path = Path("internhunter.feed.xml")
    searxng_url: str = ""

    # --- scheduled discovery (Workstream A) ---
    enable_scheduled_discovery: bool = True
    discovery_interval_min: int = 1440
    # --- scheduled rating ---
    enable_scheduled_rating: bool = True  # embedding re-rank (cheap, no LLM)
    enable_scheduled_llm_rating: bool = True  # LLM deep-read (uses Claude quota)
    rating_interval_min: int = 360  # every 6h (aligns with Claude usage-limit windows)
    llm_rating_top_k: int = 300  # jobs LLM-rated per scheduled batch
    usajobs_api_key: str = ""
    findwork_api_key: str = ""

    # --- anti-slop quality reading (Workstream B) ---
    quality_top_k: int = 40  # LLM judge reads at most this many borderline jobs per run
    quality_min_chars: int = 300  # below this a description is "content-free"
    quality_ghost_days: int = 45  # open longer than this trends toward "ghost"
    dashboard_hide_low_quality: bool = True  # default-on dashboard toggle (never deletes)

    # --- contact discovery ---
    # Which company_slugs to enrich: gate to high-fit/notifiable jobs by default.
    contacts_min_fit: float = 0.0
    contacts_max_per_company: int = 16
    contacts_methods: str = "searxng,github,ats_raw,team,registries"  # +staffspy optional
    enrich_use_browser: bool = False  # flip enable_browser for team-page / staffspy scrapes
    # GitHub: optional free PAT lifts the rate limit 60 -> 5000 req/hr.
    github_token: str = ""
    # Optional GitHub code-search discovery channel. OFF by default to keep the core
    # keyless: code search REQUIRES github_token, so this is a no-op without one.
    github_code_search: bool = False
    # Email verification — on by default; all checks are HTTPS (work despite blocked port 25).
    verify_emails: bool = True  # GitHub commit-search + Gravatar + holehe
    smtp_verify_host: str = ""  # set only if a port-25-capable relay exists; else SMTP is skipped
    smtp_verify_from: str = "verify@example.com"
    # StaffSpy (aggressive): path to a saved LinkedIn session cookie; inert if missing.
    staffspy_session: Path = Path("staffspy_session.pkl")
    # Optional outbound proxy applied to httpx + browser (empty = direct, residential IP).
    http_proxy: str = ""
    # Local OpenAI-compatible LLM (e.g. llama.cpp server) for role classification.
    llm_base_url: str = ""

    # --- round-3 net-new finding ---
    # SEC EDGAR Form D channel: required contact email in the UA header per SEC policy.
    edgar_days: int = 14
    edgar_user_agent: str = ""  # e.g. "InternHunter you@example.com" (falls back to default UA)
    # Company-similarity expansion.
    similar_top_k: int = 8
    similar_max_crawls: int = 60
    # Telegram public job channels (comma list of channel slugs; empty = inert).
    telegram_channels: str = ""
    # M365 GetCredentialType per-mailbox HTTPS verification (gray-area enumeration; opt-out).
    m365_verify: bool = True


def get_settings() -> Settings:
    return Settings()
