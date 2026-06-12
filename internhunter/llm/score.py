from __future__ import annotations

import hashlib
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Job, Score
from internhunter.llm.client import LlmBackend, LlmCache, complete, extract_json
from internhunter.match.prefilter import load_profile_text

_DESC_LIMIT = 4000


def _job_text(job: Job) -> str:
    return f"{job.title}\n{job.company or ''}\n{job.description_text}".strip()


def build_prompt(profile_text: str, job: Job) -> str:
    description = job.description_text[:_DESC_LIMIT]
    location = job.location_normalized or job.location_raw or "Unknown"
    return (
        "Candidate profile:\n"
        f"{profile_text}\n\n"
        "Job posting:\n"
        f"Title: {job.title}\n"
        f"Company: {job.company or 'Unknown'}\n"
        f"Location: {location}\n"
        f"Description:\n{description}\n\n"
        "Return ONLY a JSON object with this exact shape:\n"
        '{"fit": <int 0-100>, "matched": [<requirement strings the candidate meets>], '
        '"missing": [<requirements not met>], "rationale": "<1-2 sentence rationale>"}'
    )


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def parse_score(text: str) -> dict[str, Any]:
    data = extract_json(text)
    try:
        fit = int(data.get("fit", 0))
    except (TypeError, ValueError):
        fit = 0
    fit = max(0, min(100, fit))
    return {
        "fit": fit,
        "matched": _as_str_list(data.get("matched")),
        "missing": _as_str_list(data.get("missing")),
        "rationale": str(data.get("rationale", "")),
    }


def _input_hash(profile_text: str, job: Job) -> str:
    raw = f"{profile_text}\n\n{_job_text(job)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _upsert_score(
    session: Session,
    job_uid: str,
    input_hash: str,
    model: str,
    parsed: dict[str, Any],
) -> None:
    existing = session.scalar(
        select(Score).where(Score.job_uid == job_uid, Score.input_hash == input_hash)
    )
    fit = float(parsed["fit"])
    if existing is None:
        session.add(
            Score(
                job_uid=job_uid,
                fit_score=fit,
                matched=parsed["matched"],
                missing=parsed["missing"],
                rationale=parsed["rationale"],
                model=model,
                input_hash=input_hash,
            )
        )
    else:
        existing.fit_score = fit
        existing.matched = parsed["matched"]
        existing.missing = parsed["missing"]
        existing.rationale = parsed["rationale"]
        existing.model = model


def llm_score_jobs(
    session: Session,
    backend: LlmBackend,
    profile_text: str | None = None,
    settings: Settings | None = None,
    top_k: int = 20,
    cache: LlmCache | None = None,
) -> int:
    resolved = settings or get_settings()
    profile = (
        profile_text
        if profile_text is not None
        else load_profile_text(resolved.profile_path)
    )
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.is_internship.is_(True))
            .order_by(Job.discovery_score.desc().nulls_last())
            .limit(top_k)
        )
    )
    model = f"llm:{resolved.llm_model}"
    scored = 0
    for job in jobs:
        try:
            prompt = build_prompt(profile, job)
            reply = complete(prompt, backend, cache=cache, model=resolved.llm_model)
            parsed = parse_score(reply)
            _upsert_score(session, job.job_uid, _input_hash(profile, job), model, parsed)
        except Exception as exc:
            logger.warning("llm score failed for {}: {}", job.job_uid, exc)
            continue
        scored += 1
    session.commit()
    return scored
