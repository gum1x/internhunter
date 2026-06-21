import asyncio

import pytest

from internhunter.apply.applicant import Applicant
from internhunter.apply.pipeline import process_job
from internhunter.apply.submit.base import FormSpec, SubmitResult, register_submitter, Submitter
from internhunter.apply.fields import FormField
from internhunter.config.settings import Settings


class _Job:
    job_uid = "u1"; ats = "fake_easy"; board_token = "t"; source_job_id = "1"
    company = "Acme"; company_slug = "acme"; title = "SWE Intern"
    description_text = "Build things."; canonical_url = "https://x/y"


class _Backend:
    def generate(self, prompt, system=None, max_tokens=1024):
        return "[]" if "auditor" in prompt.lower() else "TAILORED RESUME\n- Build things"


@register_submitter
class _EasySubmitter(Submitter):
    ats = "fake_easy"
    async def probe_form(self, job, ctx):
        return FormSpec(fields=[FormField("name", "Full Name", "text", True),
                                FormField("resume", "Resume", "file", True)])
    async def submit(self, job, ctx, payload, resume_path):
        return SubmitResult(status="submitted", confirmation="C1")


@register_submitter
class _HardSubmitter(Submitter):
    ats = "fake_hard"
    async def probe_form(self, job, ctx):
        return FormSpec(fields=[FormField("q1", "Why us?", "textarea", True)])
    async def submit(self, job, ctx, payload, resume_path):
        raise AssertionError("must not submit when unknown required fields exist")


A = Applicant(full_name="Jane", email="j@x.com", phone="5", work_authorization="US Citizen",
              requires_sponsorship=False, location="", linkedin_url="", github_url="",
              portfolio_url="", school="", grad_date="")


def test_easy_job_submits(tmp_path):
    out = asyncio.run(process_job(_Job(), ctx=None, backend=_Backend(), applicant=A,
                                  profile="python", base_resume="EXPERIENCE\n- Build things",
                                  settings=Settings(cache_dir=tmp_path), dry_run=False))
    assert out.status == "submitted" and out.confirmation == "C1"
    assert out.resume_path and out.resume_path.endswith(".pdf")


def test_unknown_field_routes_to_review(tmp_path):
    job = _Job(); job.ats = "fake_hard"
    out = asyncio.run(process_job(job, ctx=None, backend=_Backend(), applicant=A,
                                  profile="python", base_resume="x",
                                  settings=Settings(cache_dir=tmp_path), dry_run=False))
    assert out.status == "needs_review"


def test_unknown_ats_routes_to_review(tmp_path):
    job = _Job(); job.ats = "no_adapter_ats"
    out = asyncio.run(process_job(job, ctx=None, backend=_Backend(), applicant=A,
                                  profile="python", base_resume="x",
                                  settings=Settings(cache_dir=tmp_path), dry_run=False))
    assert out.status == "needs_review" and "no adapter" in (out.reason or "")
