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
    usajobs_api_key: str = ""  # unused (keyless ethos) — USAJobs goes through the browser
    findwork_api_key: str = ""

    # --- external listing ingestors (aggregators / custom careers sites) ---
    # All ingestors below are keyless (no login). Page caps default to 0 = scrape every page
    # until the source runs dry (bounded by an internal safety ceiling per module).
    # LinkedIn keyless guest jobs API.
    linkedin_locations: str = (
        "United States,Remote,San Francisco Bay Area,New York City,Seattle,"
        "Austin,Boston,Los Angeles,Chicago,Atlanta,Denver,Washington DC"
    )
    linkedin_keywords: str = (
        'intern,co-op,"summer intern","software engineer intern","engineering intern"'
    )
    linkedin_max_pages: int = 0  # 25 cards per page; 0 = full scrape
    enable_linkedin_auth: bool = True  # authenticated search when a session exists / can be created
    # USAJobs federal — keyless via the stealth browser (the public HTML is JS-rendered).
    usajobs_max_pages: int = 0
    # Big-company custom career sites (keyless JSON APIs). Comma list; empty = all known.
    # Default is the two whose public JSON APIs actually work keyless; google (API
    # deprecated), microsoft (moved + broken TLS cert), and apple (Akamai bot-wall) are
    # opt-in only — add them here if/when their endpoints become reachable again.
    bigco_companies: str = "amazon,netflix"
    # University career portals: public-page JSON-LD harvest seed list.
    university_list_path: Path | None = None  # None -> registry/universities.jsonl
    # Indeed — keyless stealth-browser scrape (no login; needs a browser only to clear the
    # bot-wall). On by default; best-effort/fragile and can hit IP rate limits at scale.
    enable_indeed: bool = True
    indeed_locations: str = ""  # comma list; "" = nationwide
    indeed_max_pages: int = 0  # 10 cards per page; 0 = full scrape
    # Handshake — authenticated. Session auto-created from edu pool when possible.
    handshake_session: Path = Path("handshake_session.json")
    handshake_max_pages: int = 5
    handshake_edu_pool: str = ""  # comma user:pass@domain pairs for unattended bootstrap
    enable_handshake_auto: bool = True
    # Session automation (LinkedIn auth + Handshake bootstrap).
    sessions_dir: Path = Path("data/sessions")
    enable_session_refresh: bool = True
    session_signup_max_attempts: int = 3

    # --- Wave 1: more discovery (all keyless) ---
    # Bulk certificate-transparency enumeration (every company on a subdomain-per-company ATS).
    enable_crt_bulk: bool = True
    crt_bulk_max_per_ats: int = 5000
    # Bluesky keyless AT-Protocol post search ('|'-separated queries; empty = defaults).
    bluesky_queries: str = ""
    # Reddit keyless JSON subreddits (comma list; empty = defaults).
    reddit_subreddits: str = "internships,csMajors,cscareerquestions"
    # EURES (EU public jobs) — keyless POST search; pages per keyword pass.
    eures_max_pages: int = 5
    # Bundesagentur für Arbeit (Germany) — keyless (public X-API-Key constant).
    arbeitsagentur_max_pages: int = 5
    # Web Data Commons schema.org JobPosting dataset (gzip N-Quads). Empty = OFF (heavy/monthly);
    # set to the verified dataset URL from webdatacommons.org/structureddata to enable.
    web_data_commons_url: str = ""
    # DNS CNAME -> ATS board resolution.
    board_resolve_limit: int = 500
    # git-commit contact mining: bare-clone this many top repos per company.
    git_commit_max_repos: int = 5

    # --- Wave 1: in-process anti-block (no proxies, $0) ---
    # On a 403 (TLS-level bot wall), retry GETs once with a browser fingerprint via curl_cffi.
    enable_curl_cffi: bool = True

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

    # --- Pillar 1: Greenhouse global job-ID frontier crawler ---
    # How many recent IDs below the live frontier to probe per run (~2.8k IDs/day published).
    # The checkpoint makes steady-state runs cheap; only the first run walks a full window.
    greenhouse_frontier_window: int = 1500
    greenhouse_frontier_max_window: int = 20000  # hard cap so a bad --limit can't run forever
    greenhouse_frontier_interval_min: int = 60  # scheduled cadence (freshness lever)
    enable_greenhouse_frontier: bool = True  # independent of the daily discover-all toggle

    # reresolve re-fetches up to 2000 ats='listing' URLs; many are slow JS career portals
    # clustered on a few hosts (throttled by per_host_concurrency), so the full pass can run
    # ~30min and stall discover-all. Cap the wall-clock; unprocessed rows stay 'listing' and
    # get retried next run.
    reresolve_budget_seconds: float = 600.0
    # crt.sh bulk discovery (careers subdomain enumeration).
    crtsh_max_domains: int = 50
    crtsh_domain_delay_seconds: float = 1.5
    # YC / VC company-list discovery limits.
    yc_discovery_limit: int = 400
    vc_discovery_limit: int = 600

    # --- Pillar 2: government hiring-disclosure intelligence (OFLC LCA/PERM + SBIR/STTR) ---
    # SOC prefixes counted as "tech" hiring. 15-12xx = 2018-SOC software/CS; 15-11xx covers the
    # 2010-SOC software-developer codes used in pre-FY2020 disclosure files.
    oflc_soc_prefixes: str = "15-11,15-12"
    # OFLC LCA disclosure .xlsx URL (data.gov mirror) or local path; empty = pass via --url.
    oflc_lca_url: str = ""
    sbir_api_url: str = "https://api.www.sbir.gov/public/api/awards"
    # dol.gov / sbir.gov 403 plain bots; a descriptive UA (ideally with a contact email) helps.
    disclosure_user_agent: str = ""


def get_settings() -> Settings:
    return Settings()
