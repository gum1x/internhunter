from __future__ import annotations

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
    assert {job.id for job in jobs} == {"poll-tier-A", "poll-tier-B", "poll-tier-C"}
    for job in jobs:
        tier = job.id.removeprefix("poll-tier-")
        minutes = job.trigger.interval.total_seconds() / 60
        assert minutes == _TIER_INTERVALS_MIN[tier]


def test_build_scheduler_not_running() -> None:
    scheduler = build_scheduler()
    assert scheduler.running is False
