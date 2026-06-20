from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Board, Company, Job, Score
from internhunter.match.embed import EmbeddingCache, Encoder, cosine_matrix, embed_texts
from internhunter.match.prefilter import load_candidate_profile
from internhunter.match.rarity import discovery_score, freshness_score, rarity_score


def _job_text(job: Job) -> str:
    return f"{job.title}. {job.description_text}".strip()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _upsert_score(
    session: Session, job_uid: str, fit: float, model: str, input_hash: str
) -> None:
    existing = session.scalar(
        select(Score).where(Score.job_uid == job_uid, Score.input_hash == input_hash)
    )
    if existing is None:
        session.add(
            Score(job_uid=job_uid, fit_score=fit, model=model, input_hash=input_hash)
        )
    else:
        existing.fit_score = fit
        existing.model = model


def score_jobs(
    session: Session,
    encoder: Encoder,
    profile_text: str | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> int:
    resolved = settings or get_settings()
    profile = (
        profile_text
        if profile_text is not None
        else load_candidate_profile(resolved)
    )
    moment = now or datetime.now(UTC)
    jobs = list(session.scalars(select(Job)))
    if not jobs:
        return 0

    cache = EmbeddingCache(resolved.cache_dir, resolved.embed_model)
    profile_vec = embed_texts([profile], encoder, cache)
    job_matrix = embed_texts([_job_text(job) for job in jobs], encoder, cache)
    sims = cosine_matrix(profile_vec, job_matrix)[0]

    board_sizes = {
        board.id: board.total_jobs_seen for board in session.scalars(select(Board))
    }
    # Companies with a verified government hiring-disclosure signal (OFLC/SBIR) are proven
    # active tech employers -> a small, capped boost so legitimate, hiring companies float up.
    hiring_slugs = set(
        session.scalars(
            select(Company.company_slug).where(
                func.json_extract(Company.notes, "$.disclosure").isnot(None)
            )
        )
    )
    input_hash = hashlib.sha1(profile.encode()).hexdigest()
    model_name = f"prefilter:{resolved.embed_model}"

    for i, (job, raw_fit) in enumerate(zip(jobs, sims, strict=True)):
        fit = max(0.0, min(1.0, float(raw_fit)))
        posted = _aware(job.posted_at) or _aware(job.first_seen_at)
        fresh = freshness_score(posted, moment)
        board_total = board_sizes.get(job.board_id) if job.board_id is not None else None
        rar = rarity_score(job.times_seen_elsewhere, board_total)
        job.freshness_score = fresh
        job.rarity_score = rar
        score_value = discovery_score(fit, fresh, rar)
        if job.is_internship and job.company_slug in hiring_slugs:
            score_value = min(1.0, score_value + 0.05)
        job.discovery_score = score_value
        _upsert_score(session, job.job_uid, fit, model_name, input_hash)
        # Commit in chunks so this whole-corpus re-rank doesn't hold the write lock for
        # its entire run (which would stall the dashboard's tracker writes).
        if (i + 1) % 2000 == 0:
            session.commit()

    session.commit()
    return len(jobs)
