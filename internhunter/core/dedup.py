from __future__ import annotations

from datetime import UTC, datetime
from difflib import SequenceMatcher

from internhunter.core.models import NormalizedJob

_TIER_A_ATS = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "recruitee",
        "workable",
        "personio",
    }
)


def duplicate_key(job: NormalizedJob) -> tuple[str, str]:
    return (job.company_slug, job.title_normalized)


def _locations_compatible(a: NormalizedJob, b: NormalizedJob) -> bool:
    if a.is_remote or b.is_remote:
        return True
    if a.location_normalized is None or b.location_normalized is None:
        return True
    return a.location_normalized == b.location_normalized


def is_fuzzy_duplicate(a: NormalizedJob, b: NormalizedJob, threshold: float = 0.9) -> bool:
    if a.company_slug != b.company_slug:
        return False
    ratio = SequenceMatcher(None, a.title_normalized, b.title_normalized).ratio()
    if ratio < threshold:
        return False
    return _locations_compatible(a, b)


def _ats_rank(ats: str) -> int:
    return 0 if ats in _TIER_A_ATS else 1


def _max_datetime() -> datetime:
    return datetime.max.replace(tzinfo=UTC)


def _canonical_sort_key(job: NormalizedJob) -> tuple[int, datetime, datetime]:
    posted = job.posted_at if job.posted_at is not None else _max_datetime()
    return (_ats_rank(job.ats), posted, job.first_seen_at)


def collapse(jobs: list[NormalizedJob]) -> tuple[list[NormalizedJob], int]:
    by_hash: dict[str, NormalizedJob] = {}
    deduped: list[NormalizedJob] = []
    exact_merged = 0
    for job in jobs:
        if job.url_hash in by_hash:
            exact_merged += 1
            continue
        by_hash[job.url_hash] = job
        deduped.append(job)

    groups: list[list[NormalizedJob]] = []
    for job in deduped:
        placed = False
        for group in groups:
            if any(is_fuzzy_duplicate(job, member) for member in group):
                group.append(job)
                placed = True
                break
        if not placed:
            groups.append([job])

    canonicals: list[NormalizedJob] = []
    fuzzy_merged = 0
    for group in groups:
        canonical = min(group, key=_canonical_sort_key)
        canonical.times_seen_elsewhere = len(group) - 1
        fuzzy_merged += len(group) - 1
        canonicals.append(canonical)

    return (canonicals, exact_merged + fuzzy_merged)
