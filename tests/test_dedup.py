from __future__ import annotations

from datetime import UTC, datetime

from internhunter.core.dedup import collapse, duplicate_key, is_fuzzy_duplicate
from internhunter.core.models import NormalizedJob


def _job(
    *,
    ats: str,
    url: str,
    company_slug: str = "acme",
    title: str = "Software Engineering Intern",
    title_normalized: str = "software engineering intern",
    location_normalized: str | None = "berlin, de",
    is_remote: bool = False,
    posted_at: datetime | None = None,
    first_seen_at: datetime | None = None,
) -> NormalizedJob:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return NormalizedJob(
        job_uid=f"{ats}:{url}",
        ats=ats,
        board_token="acme",
        canonical_url=url,
        url_hash=url,
        company_slug=company_slug,
        title=title,
        title_normalized=title_normalized,
        location_normalized=location_normalized,
        is_remote=is_remote,
        posted_at=posted_at,
        first_seen_at=first_seen_at or now,
        last_seen_at=first_seen_at or now,
    )


def test_duplicate_key() -> None:
    job = _job(ats="greenhouse", url="a")
    assert duplicate_key(job) == ("acme", "software engineering intern")


def test_fuzzy_duplicate_collapses_prefers_tier_a() -> None:
    a = _job(ats="bamboohr", url="r1", title_normalized="software engineer intern")
    b = _job(ats="greenhouse", url="g1", title_normalized="software engineering intern")

    assert is_fuzzy_duplicate(a, b) is True

    canonicals, merged = collapse([b, a])

    assert len(canonicals) == 1
    assert merged == 1
    assert canonicals[0].ats == "greenhouse"
    assert canonicals[0].times_seen_elsewhere == 1


def test_canonical_tiebreak_prefers_earliest_posted_within_tier_a() -> None:
    early = datetime(2026, 1, 10, tzinfo=UTC)
    late = datetime(2026, 2, 1, tzinfo=UTC)
    later_post = _job(
        ats="greenhouse",
        url="g1",
        title_normalized="software engineering intern",
        posted_at=late,
    )
    earlier_post = _job(
        ats="lever",
        url="l1",
        title_normalized="software engineering intern",
        posted_at=early,
    )

    canonicals, merged = collapse([later_post, earlier_post])

    assert len(canonicals) == 1
    assert merged == 1
    assert canonicals[0].ats == "lever"
    assert canonicals[0].posted_at == early


def test_recruitee_treated_as_tier_a() -> None:
    recruitee = _job(ats="recruitee", url="r1", posted_at=datetime(2026, 1, 5, tzinfo=UTC))
    non_tier = _job(ats="bamboohr", url="b1", posted_at=datetime(2026, 1, 1, tzinfo=UTC))

    canonicals, merged = collapse([non_tier, recruitee])

    assert len(canonicals) == 1
    assert merged == 1
    assert canonicals[0].ats == "recruitee"


def test_different_companies_do_not_collapse() -> None:
    a = _job(ats="greenhouse", url="g1", company_slug="acme")
    b = _job(ats="lever", url="l1", company_slug="globex")

    assert is_fuzzy_duplicate(a, b) is False

    canonicals, merged = collapse([a, b])

    assert len(canonicals) == 2
    assert merged == 0


def test_exact_url_hash_dup_collapses() -> None:
    a = _job(ats="greenhouse", url="same")
    b = _job(ats="greenhouse", url="same")

    canonicals, merged = collapse([a, b])

    assert len(canonicals) == 1
    assert merged == 1
    assert canonicals[0].times_seen_elsewhere == 0


def test_incompatible_locations_not_fuzzy_duplicate_symmetric() -> None:
    a = _job(ats="greenhouse", url="g1", location_normalized="berlin, de")
    b = _job(ats="lever", url="l1", location_normalized="munich, de")

    assert is_fuzzy_duplicate(a, b) is False
    assert is_fuzzy_duplicate(b, a) is False

    canonicals, merged = collapse([a, b])
    assert len(canonicals) == 2
    assert merged == 0


def test_remote_makes_locations_compatible_symmetric() -> None:
    a = _job(ats="greenhouse", url="g1", location_normalized="berlin, de", is_remote=True)
    b = _job(ats="lever", url="l1", location_normalized="munich, de", is_remote=False)

    assert is_fuzzy_duplicate(a, b) is True
    assert is_fuzzy_duplicate(b, a) is True


def test_three_way_group_times_seen_elsewhere() -> None:
    a = _job(ats="greenhouse", url="g1", title_normalized="software engineering intern")
    b = _job(ats="lever", url="l1", title_normalized="software engineer intern")
    c = _job(ats="ashby", url="ab1", title_normalized="software engineering intern")

    canonicals, merged = collapse([a, b, c])

    assert len(canonicals) == 1
    assert merged == 2
    assert canonicals[0].times_seen_elsewhere == 2


def test_below_threshold_stays_separate() -> None:
    a = _job(ats="greenhouse", url="g1", title_normalized="software engineering intern")
    b = _job(ats="lever", url="l1", title_normalized="data scientist new grad")

    assert is_fuzzy_duplicate(a, b) is False

    canonicals, merged = collapse([a, b])

    assert len(canonicals) == 2
    assert merged == 0
