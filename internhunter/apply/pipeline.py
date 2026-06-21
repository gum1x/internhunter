from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from internhunter.apply.applicant import Applicant, load_applicant, validate_applicant
from internhunter.apply.fields import classify_fields
from internhunter.apply.guardrails import skip_reason
from internhunter.apply.render import render_resume_pdf
from internhunter.apply.submit.base import get_submitter
import internhunter.apply.submit.greenhouse  # noqa: F401  (registration)
import internhunter.apply.submit.lever       # noqa: F401  (registration)
from internhunter.config.settings import Settings, get_settings
from internhunter.resume.tailor import TailorRequest, tailor_resume

TIER_A = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters",
          "recruitee", "personio", "pinpoint")


@dataclass
class ApplyOutcome:
    job_uid: str
    status: str
    reason: str | None = None
    resume_path: str | None = None
    confirmation: str | None = None


async def process_job(job, *, ctx, backend, applicant: Applicant, profile: str,
                      base_resume: str, settings: Settings, dry_run: bool) -> ApplyOutcome:
    submitter = get_submitter(job.ats)
    if submitter is None:
        return ApplyOutcome(job.job_uid, "needs_review", reason=f"no adapter for ats={job.ats}")

    spec = await submitter.probe_form(job, ctx)
    if spec.requires_account or spec.captcha_detected:
        return ApplyOutcome(job.job_uid, "needs_review", reason="login wall / captcha")

    payload, unknown = classify_fields(spec.fields, applicant)
    if unknown:
        labels = ", ".join(f.label for f in unknown)
        return ApplyOutcome(job.job_uid, "needs_review", reason=f"unfillable fields: {labels}")

    tailored = tailor_resume(
        TailorRequest(job_uid=job.job_uid, job_text=f"{job.title}. {job.description_text}",
                      base_resume=base_resume, profile=profile),
        backend,
    )
    out_dir = Path(settings.cache_dir) / "resumes"
    resume_path = render_resume_pdf(tailored.tailored_resume, out_dir / f"{job.job_uid}.pdf")

    if dry_run:
        return ApplyOutcome(job.job_uid, "would_submit", reason="; ".join(tailored.warnings) or None,
                            resume_path=str(resume_path))

    result = await submitter.submit(job, ctx, payload, resume_path)
    return ApplyOutcome(job.job_uid, result.status, reason=result.reason,
                        resume_path=str(resume_path), confirmation=result.confirmation)


def select_candidates(session, settings: Settings):
    from sqlalchemy import select
    from internhunter.core.db import Application, Job, Score

    threshold = settings.auto_apply_min_fit * 100  # llm:% fit_score is 0-100
    applied = select(Application.job_uid)
    fit = (select(Score.job_uid).where(Score.model.like("llm:%"),
                                       Score.fit_score >= threshold))
    return list(session.scalars(
        select(Job).where(
            Job.is_internship.is_(True),
            Job.ats.in_(TIER_A),
            Job.job_uid.in_(fit),
            Job.job_uid.not_in(applied),
            (Job.quality_verdict.is_(None)) | (Job.quality_verdict != "slop"),
        ).order_by(Job.discovery_score.desc().nulls_last())
    ))


async def auto_apply(*, settings: Settings | None = None, limit: int | None = None,
                     dry_run: bool = False) -> list[ApplyOutcome]:
    import random

    from internhunter.core.db import Application, get_session
    from internhunter.core.fetch import build_fetch_context
    from internhunter.llm.client import LlmCache, get_backend
    from internhunter.match.prefilter import load_candidate_profile, load_profile_text
    from internhunter.resume.load import load_resume_text

    resolved = settings or get_settings()
    applicant = load_applicant(resolved)
    missing = validate_applicant(applicant)
    if missing:
        return [ApplyOutcome("", "failed", reason=f"missing applicant fields: {missing}")]

    profile = load_profile_text(resolved.profile_path)
    base_resume = load_resume_text(resolved.resume_path) or ""
    if not base_resume.strip():
        return [ApplyOutcome("", "failed", reason="no base resume found")]

    backend = get_backend(resolved)
    cache = LlmCache(resolved.cache_dir)
    outcomes: list[ApplyOutcome] = []
    session = get_session()
    try:
        candidates = select_candidates(session, resolved)
        if limit is not None:
            candidates = candidates[:limit]
        async with build_fetch_context(resolved) as ctx:
            for job in candidates:
                reason = skip_reason(session, job, applicant, resolved)
                if reason is not None:
                    if reason == "daily cap reached" or reason.startswith("auto-apply disabled"):
                        break  # hard stop for the whole run
                    continue   # per-job skip (already applied / ineligible / company cap)
                outcome = await process_job(job, ctx=ctx, backend=backend, applicant=applicant,
                                            profile=profile, base_resume=base_resume,
                                            settings=resolved, dry_run=dry_run)
                _record(session, job, outcome)
                outcomes.append(outcome)
                if not dry_run and outcome.status == "submitted":
                    await asyncio.sleep(resolved.auto_apply_delay_seconds * (1 + random.random()))
    finally:
        session.close()
    return outcomes


def _record(session, job, outcome: ApplyOutcome) -> None:
    from datetime import UTC, datetime

    from internhunter.core.db import Application

    note = outcome.reason or ""
    if outcome.confirmation:
        note = f"{note} (confirmation={outcome.confirmation})".strip()
    app = Application(
        job_uid=job.job_uid, status=outcome.status, company=job.company,
        company_slug=job.company_slug, role=job.title, link=job.canonical_url,
        resume_path=outcome.resume_path, notes=note or None,
        applied_at=datetime.now(UTC) if outcome.status == "submitted" else None,
    )
    session.add(app)
    session.commit()
