from __future__ import annotations

from internhunter.discovery.listing_common import ListingJob, board_refs, listing_to_job


def test_listing_to_job_keeps_internship_and_tags_source() -> None:
    job = listing_to_job(
        ListingJob(
            title="Marketing Intern",
            company="Acme",
            url="https://example.com/jobs/1",
            location="Remote",
            source="linkedin",
        )
    )
    assert job is not None
    assert job.is_internship is True
    assert job.ats == "listing"
    assert job.is_remote is True
    assert job.raw["source"] == "linkedin"


def test_listing_to_job_upgrades_real_ats() -> None:
    job = listing_to_job(
        ListingJob(
            title="Data Science Intern",
            company="Acme",
            url="https://boards.greenhouse.io/acme/jobs/9",
            source="bigco:google",
        )
    )
    assert job is not None
    assert job.ats == "greenhouse"
    assert job.board_token == "acme"


def test_listing_to_job_filters_non_internship() -> None:
    assert (
        listing_to_job(
            ListingJob(
                title="Senior Staff Engineer",
                company="Acme",
                url="https://example.com/x",
                source="indeed",
            )
        )
        is None
    )


def test_listing_to_job_requires_title_and_url() -> None:
    assert listing_to_job(ListingJob(title="", company="A", url="https://x/y")) is None
    assert listing_to_job(ListingJob(title="Intern", company="A", url="")) is None


def test_board_refs_recovers_only_real_ats() -> None:
    jobs = [
        listing_to_job(ListingJob("Intern", "Acme", "https://jobs.lever.co/acme/1", source="x")),
        listing_to_job(ListingJob("Intern", "Beta", "https://beta.com/careers/1", source="x")),
    ]
    refs = board_refs([j for j in jobs if j is not None])
    assert [(r.ats, r.token) for r in refs] == [("lever", "acme")]
