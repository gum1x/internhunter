from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from internhunter.config.settings import Settings
from internhunter.core.runner import run_poll

_TIER_INTERVALS_MIN: dict[str, int] = {"A": 30, "B": 120, "C": 360}

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
    return scheduler


def run_now(ats: str | None = None, settings: Settings | None = None) -> None:
    run_poll(ats=[ats] if ats else None, settings=settings)
