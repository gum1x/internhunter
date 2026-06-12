from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.job_apis import ApiJob, api_job_to_job, fetch_api_jobs


def test_api_job_to_job_keeps_internships() -> None:
    job = api_job_to_job(
        ApiJob(
            title="Data Science Intern",
            company="Acme",
            url="https://boards.greenhouse.io/acme/jobs/9",
            location="Remote",
            posted="2026-05-01T00:00:00",
            source="remotive",
        )
    )
    assert job is not None
    assert job.is_internship is True
    assert job.ats == "greenhouse"
    assert job.board_token == "acme"
    assert job.is_remote is True


def test_api_job_to_job_filters_non_internships() -> None:
    job = api_job_to_job(
        ApiJob(
            title="Senior Staff Engineer",
            company="Acme",
            url="https://acme.com/jobs/1",
            location=None,
            posted=None,
            source="arbeitnow",
        )
    )
    assert job is None


async def test_fetch_api_jobs_remotive(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses["https://remotive.com/api/remote-jobs?search=intern"] = httpx.Response(
        200,
        text=json.dumps(
            {
                "jobs": [
                    {
                        "title": "Marketing Intern",
                        "company_name": "Beta",
                        "url": "https://jobs.lever.co/beta/1",
                        "candidate_required_location": "USA",
                        "publication_date": "2026-04-01",
                    }
                ]
            }
        ),
    )
    jobs = await fetch_api_jobs(ctx, sources=["remotive"])
    assert len(jobs) == 1
    assert jobs[0].company == "Beta"
    assert jobs[0].url == "https://jobs.lever.co/beta/1"
