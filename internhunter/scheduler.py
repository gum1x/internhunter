from __future__ import annotations

from importlib import import_module

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from internhunter.config.settings import Settings, get_settings
from internhunter.core.runner import run_discovery, run_poll, run_score, run_score_llm
from internhunter.sources.base import SOURCE_REGISTRY

_TIER_INTERVALS_MIN: dict[str, int] = {"A": 30, "B": 120, "C": 360}
_CONTACTS_INTERVAL_MIN = 720  # enrich freshly-discovered companies twice a day
_SESSION_REFRESH_INTERVAL_MIN = 360


def _load_sources() -> None:
    import_module("internhunter.sources.tier_a")
    import_module("internhunter.sources.tier_b")
    import_module("internhunter.sources.tier_c")


def tier_for_ats(ats: str) -> str:
    _load_sources()
    source = SOURCE_REGISTRY.get(ats)
    if source is not None:
        return str(source.tier)
    return "B"


def _tier_members() -> dict[str, list[str]]:
    _load_sources()
    members: dict[str, list[str]] = {"A": [], "B": [], "C": []}
    for ats, source in sorted(SOURCE_REGISTRY.items()):
        members[str(source.tier)].append(ats)
    return members


def all_registered_ats() -> list[str]:
    _load_sources()
    return sorted(SOURCE_REGISTRY)


def build_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    members = _tier_members()
    for tier, minutes in _TIER_INTERVALS_MIN.items():
        scheduler.add_job(
            run_poll,
            trigger=IntervalTrigger(minutes=minutes),
            kwargs={"ats": members[tier], "settings": settings},
            id=f"poll-tier-{tier}",
        )

    from internhunter.contacts.runner import run_find_contacts

    scheduler.add_job(
        run_find_contacts,
        trigger=IntervalTrigger(minutes=_CONTACTS_INTERVAL_MIN),
        kwargs={"settings": settings},
        id="find-contacts",
    )

    resolved = settings or get_settings()
    if resolved.enable_scheduled_discovery:
        scheduler.add_job(
            run_discovery,
            trigger=IntervalTrigger(minutes=resolved.discovery_interval_min),
            kwargs={"settings": settings},
            id="discover-all",
        )
    if resolved.enable_greenhouse_frontier:
        from internhunter.discovery.greenhouse_frontier import run_greenhouse_frontier

        scheduler.add_job(
            run_greenhouse_frontier,
            trigger=IntervalTrigger(minutes=resolved.greenhouse_frontier_interval_min),
            kwargs={"settings": settings},
            id="greenhouse-frontier",
        )
    if resolved.enable_scheduled_rating:
        scheduler.add_job(
            run_score,
            trigger=IntervalTrigger(minutes=resolved.rating_interval_min),
            kwargs={"settings": settings},
            id="score",
        )
    if resolved.enable_scheduled_llm_rating:
        scheduler.add_job(
            run_score_llm,
            trigger=IntervalTrigger(minutes=resolved.rating_interval_min),
            kwargs={"settings": settings},
            id="score-llm",
        )
    if resolved.enable_scheduled_notify:
        from internhunter.notify.runner import run_notify

        scheduler.add_job(
            run_notify,
            trigger=IntervalTrigger(minutes=resolved.notify_interval_min),
            kwargs={"settings": settings},
            id="notify",
        )
    if resolved.enable_session_refresh:
        from internhunter.sessions.refresh import run_refresh_sessions

        scheduler.add_job(
            run_refresh_sessions,
            trigger=IntervalTrigger(minutes=_SESSION_REFRESH_INTERVAL_MIN),
            kwargs={"settings": settings},
            id="refresh-sessions",
        )
    return scheduler


def run_now(ats: str | None = None, settings: Settings | None = None) -> None:
    run_poll(ats=[ats] if ats else None, settings=settings)