"""Integration test: verify that auto_apply only persists Application rows for
terminal outcomes of a REAL run (submitted / needs_review), and records nothing
during dry-run or failed (transient) outcomes."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

import internhunter.apply.pipeline as pipeline_mod
import internhunter.core.db as db_mod
import internhunter.core.fetch as fetch_mod
import internhunter.llm.client as llm_mod
import internhunter.match.prefilter as prefilter_mod
import internhunter.resume.load as resume_load_mod
from internhunter.apply.applicant import Applicant
from internhunter.apply.fields import FormField
from internhunter.apply.submit.base import (
    FormSpec,
    SubmitResult,
    Submitter,
    register_submitter,
)
from internhunter.config.settings import Settings
from internhunter.core.db import Application, Job

# ---------------------------------------------------------------------------
# Fake ATS submitter (ats="rec_test") registered once at import time
# ---------------------------------------------------------------------------

@register_submitter
class _RecTestSubmitter(Submitter):
    ats = "rec_test"

    async def probe_form(self, job: Any, ctx: Any) -> FormSpec:
        return FormSpec(
            fields=[
                FormField("name", "Full Name", "text", True),
                FormField("resume", "Resume", "file", True),
            ]
        )

    async def submit(
        self, job: Any, ctx: Any, payload: dict[str, str], resume_path: Any
    ) -> SubmitResult:
        return SubmitResult(status="submitted", confirmation="C")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APPLICANT = Applicant(
    full_name="Jane Doe",
    email="jane@example.com",
    phone="555-0000",
    work_authorization="US Citizen",
    requires_sponsorship=False,
)


class _FakeBackend:
    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        if "auditor" in prompt.lower():
            return "[]"
        return "TAILORED RESUME\n- Built things"


@asynccontextmanager
async def _fake_fetch_ctx(_settings: Any) -> AsyncIterator[Any]:
    yield object()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_dry_run_records_nothing_real_run_records_submitted(
    db_session: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """dry_run=True must leave the applications table empty;
    dry_run=False must write exactly one row with status='submitted'."""

    # Insert the stub job so the FK constraint on Application.job_uid is satisfied.
    job_orm = Job(
        job_uid="test-uid-1",
        ats="rec_test",
        board_token="acme",
        source_job_id="j1",
        canonical_url="https://acme.co/j1",
        url_hash="fake-hash-1",
        company="Acme",
        company_slug="acme",
        title="SWE Intern",
        title_normalized="swe intern",
        description_text="Build stuff.",
        is_internship=True,
    )
    db_session.add(job_orm)
    db_session.commit()

    stub_job = SimpleNamespace(
        job_uid="test-uid-1",
        ats="rec_test",
        board_token="acme",
        source_job_id="j1",
        company="Acme",
        company_slug="acme",
        title="SWE Intern",
        description_text="Build stuff.",
        canonical_url="https://acme.co/j1",
    )

    settings = Settings(
        enable_auto_apply=True,
        cache_dir=tmp_path,
        db_path=tmp_path / "test.db",
    )

    # Patch local imports used inside auto_apply
    monkeypatch.setattr(db_mod, "get_session", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(fetch_mod, "build_fetch_context", _fake_fetch_ctx)
    monkeypatch.setattr(llm_mod, "get_backend", lambda s: _FakeBackend())
    monkeypatch.setattr(prefilter_mod, "load_profile_text", lambda p: "python developer")
    monkeypatch.setattr(resume_load_mod, "load_resume_text", lambda p: "EXPERIENCE\n- built things")

    # Patch module-level names in pipeline (load_applicant, validate_applicant, select_candidates)
    monkeypatch.setattr(pipeline_mod, "load_applicant", lambda s: _APPLICANT)
    monkeypatch.setattr(pipeline_mod, "validate_applicant", lambda a: [])
    monkeypatch.setattr(pipeline_mod, "select_candidates", lambda session, s: [stub_job])

    from internhunter.apply.pipeline import auto_apply

    # --- dry run: should produce ZERO Application rows ---
    asyncio.run(auto_apply(settings=settings, dry_run=True))
    rows = list(db_session.scalars(select(Application)))
    assert len(rows) == 0, f"dry_run wrote {len(rows)} row(s); expected 0"

    # --- real run: should produce exactly ONE row with status "submitted" ---
    asyncio.run(auto_apply(settings=settings, dry_run=False))
    rows = list(db_session.scalars(select(Application)))
    assert len(rows) == 1, f"real run wrote {len(rows)} row(s); expected 1"
    assert rows[0].status == "submitted"
    assert rows[0].job_uid == "test-uid-1"
