from __future__ import annotations

from internhunter.config.settings import Settings


def source_status(settings: Settings) -> dict[str, bool]:
    """Which contact-discovery inputs are actually configured/available right now.

    Cheap, dependency-tolerant checks so a run logs *why* a source is inert (the most
    common failure mode is an unset SearXNG URL or GitHub token, not a code bug).
    """
    methods = {m.strip() for m in settings.contacts_methods.split(",") if m.strip()}

    def _installed(mod: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    return {
        "searxng_dorking": bool(settings.searxng_url) and "searxng" in methods,
        "github_people": "github" in methods and _installed("github"),
        "github_token": bool(settings.github_token),
        "ats_raw_mining": "ats_raw" in methods,
        "team_pages": "team" in methods,
        "staffspy": "staffspy" in methods and settings.staffspy_session.exists(),
        "verify_emails": settings.verify_emails,
        "dnspython_for_domains": _installed("dns"),
        "llm_backend": bool(settings.llm_base_url) or settings.llm_backend in ("api", "cli"),
    }


def format_status(settings: Settings) -> str:
    rows = [f"  {name:24} {'✓' if ok else '✗'}" for name, ok in source_status(settings).items()]
    return "contact sources:\n" + "\n".join(rows)
