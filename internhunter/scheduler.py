from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from internhunter.config.settings import Settings, get_settings
from internhunter.core.runner import run_discovery, run_poll, run_score, run_score_llm

_TIER_INTERVALS_MIN: dict[str, int] = {"A": 30, "B": 120, "C": 360}
_CONTACTS_INTERVAL_MIN = 720  # enrich freshly-discovered companies twice a day

_TIER_A = {
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "recruitee",
    "personio",
}
_TIER_B = {
    "breezy",
    "bamboohr",
    "jobvite",
    "jazzhr",
    "zohorecruit",
    "dover",
    "rippling",
    "gem",
}
_TIER_C = {
    "workday",
    "icims",
    "ultipro",
    "oracle_cloud",
    "adp",
    "paylocity",
}


def tier_for_ats(ats: str) -> str:
    if ats in _TIER_A:
        return "A"
    if ats in _TIER_C:
        return "C"
    return "B"


def _tier_members() -> dict[str, list[str]]:
    members: dict[str, list[str]] = {"A": [], "B": [], "C": []}
    for ats in sorted(_TIER_A | _TIER_B | _TIER_C):
        members[tier_for_ats(ats)].append(ats)
    return members


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
        # Greenhouse ID-frontier runs far more often than the daily discover-all: its whole
        # value is catching brand-new postings within ~an hour, and the checkpoint keeps each
        # incremental run cheap.
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
    return scheduler


def run_now(ats: str | None = None, settings: Settings | None = None) -> None:
    run_poll(ats=[ats] if ats else None, settings=settings)
