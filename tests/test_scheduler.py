from __future__ import annotations

from internhunter.config.settings import Settings
from internhunter.scheduler import (
    _TIER_INTERVALS_MIN,
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
        "score",
        "score-llm",
    }
    for job in jobs:
        if not job.id.startswith("poll-tier-"):
            continue
        tier = job.id.removeprefix("poll-tier-")
        minutes = job.trigger.interval.total_seconds() / 60
        assert minutes == _TIER_INTERVALS_MIN[tier]


def test_scheduled_discovery_can_be_disabled() -> None:
    scheduler = build_scheduler(Settings(enable_scheduled_discovery=False))
    assert "discover-all" not in {job.id for job in scheduler.get_jobs()}


def test_build_scheduler_not_running() -> None:
    scheduler = build_scheduler()
    assert scheduler.running is False
