from __future__ import annotations

from internhunter.config.settings import Settings
from internhunter.scheduler import (
    _TIER_INTERVALS_MIN,
    all_registered_ats,
    build_scheduler,
    tier_for_ats,
)


def test_tier_for_ats() -> None:
    assert tier_for_ats("greenhouse") == "A"
    assert tier_for_ats("breezy") == "B"
    assert tier_for_ats("workday") == "C"
    assert tier_for_ats("unknown-ats") == "B"


def test_build_scheduler_jobs() -> None:
    scheduler = build_scheduler()
    jobs = scheduler.get_jobs()
    assert {job.id for job in jobs} == {
        "poll-tier-A",
        "poll-tier-B",
        "poll-tier-C",
        "find-contacts",
        "discover-all",
        "greenhouse-frontier",
        "score",
        "score-llm",
        "refresh-sessions",
    }
    for job in jobs:
        if not job.id.startswith("poll-tier-"):
            continue
        tier = job.id.removeprefix("poll-tier-")
        minutes = job.trigger.interval.total_seconds() / 60
        assert minutes == _TIER_INTERVALS_MIN[tier]


def test_scheduled_discovery_can_be_disabled() -> None:
    scheduler = build_scheduler(Settings(enable_scheduled_discovery=False))
    jobs = {job.id for job in scheduler.get_jobs()}
    assert "discover-all" not in jobs
    # The hourly frontier has its own toggle and must NOT be coupled to the daily sweep.
    assert "greenhouse-frontier" in jobs


def test_greenhouse_frontier_has_its_own_toggle() -> None:
    scheduler = build_scheduler(Settings(enable_greenhouse_frontier=False))
    assert "greenhouse-frontier" not in {job.id for job in scheduler.get_jobs()}


def test_build_scheduler_not_running() -> None:
    scheduler = build_scheduler()
    assert scheduler.running is False


def test_all_registered_ats_are_scheduled() -> None:
    scheduler = build_scheduler()
    scheduled: set[str] = set()
    for job in scheduler.get_jobs():
        if not job.id.startswith("poll-tier-"):
            continue
        scheduled.update(job.kwargs.get("ats", []))
    assert scheduled == set(all_registered_ats())
    assert "pinpoint" in scheduled
    assert "comeet" in scheduled
    assert "teamtailor" in scheduled
    assert "eightfold" in scheduled
    assert "phenom" in scheduled
    assert "successfactors" in scheduled
