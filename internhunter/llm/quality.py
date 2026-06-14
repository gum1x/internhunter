from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Job
from internhunter.llm.client import LlmBackend, LlmCache, complete, extract_json

_DESC_LIMIT = 4000
_VERDICTS = {"ok", "spam", "ghost", "agency", "mlm", "unclear"}
# Heuristic score at/above this is "clean" — skip the LLM read entirely (cheap-first).
_BORDERLINE_BELOW = 95.0

QUALITY_SYSTEM = (
    "You are a careful reviewer deciding whether an internship/early-career job posting is "
    "a REAL, worthwhile opportunity or low-quality 'slop' (scam, MLM, content-farm repost, "
    "staffing-agency lead-gen, or an evergreen 'ghost' listing that is never actually filled). "
    "Judge legitimacy and substance SEPARATELY from how niche or small the company is — a terse "
    "posting from a tiny real startup is fine. When genuinely unsure, abstain with verdict "
    "'unclear'; never guess 'ok'. Return ONLY a JSON object, no prose."
)


def build_quality_prompt(job: Job) -> str:
    # Deliberately omit the ATS/source so the model judges the CONTENT, not brand prestige.
    description = (job.description_text or "")[:_DESC_LIMIT]
    location = job.location_normalized or job.location_raw or "Unknown"
    return (
        "Internship posting to review:\n"
        f"Title: {job.title}\n"
        f"Company: {job.company or 'Unknown'}\n"
        f"Location: {location}\n"
        f"Description:\n{description or '(no description provided)'}\n\n"
        "First think in the 'reason' field, then fill the rest. Return ONLY this JSON:\n"
        '{"legit": <int 0-100>, "substance": <int 0-100>, '
        '"verdict": "ok|spam|ghost|agency|mlm|unclear", '
        '"flags": [<short strings>], "confidence": <int 0-100>, "reason": "<1-2 sentences>"}'
    )


def _clamp(value: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return 0


def parse_quality(text: str) -> dict[str, Any]:
    data = extract_json(text)
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in _VERDICTS:
        verdict = "unclear"
    flags = data.get("flags")
    flag_list = [str(f) for f in flags] if isinstance(flags, list) else []
    return {
        "legit": _clamp(data.get("legit")),
        "substance": _clamp(data.get("substance")),
        "verdict": verdict,
        "flags": flag_list,
        "confidence": _clamp(data.get("confidence")),
        "reason": str(data.get("reason", "")),
    }


def select_borderline(session: Session, top_k: int) -> list[Job]:
    """Internships the heuristic flagged as borderline and that aren't judged yet."""
    stmt = (
        select(Job)
        .where(
            Job.is_internship.is_(True),
            Job.quality_verdict.is_(None),
            or_(Job.quality_score.is_(None), Job.quality_score < _BORDERLINE_BELOW),
        )
        .order_by(Job.discovery_score.desc().nulls_last())
        .limit(top_k)
    )
    return list(session.scalars(stmt))


def judge_quality_jobs(
    session: Session,
    backend: LlmBackend,
    settings: Settings | None = None,
    top_k: int | None = None,
    cache: LlmCache | None = None,
) -> int:
    resolved = settings or get_settings()
    limit = top_k if top_k is not None else resolved.quality_top_k
    jobs = select_borderline(session, limit)
    model = f"quality:{resolved.llm_model}"
    judged = 0
    for job in jobs:
        try:
            reply = complete(
                build_quality_prompt(job),
                backend,
                system=QUALITY_SYSTEM,
                cache=cache,
                model=resolved.llm_model,
            )
            parsed = parse_quality(reply)
        except Exception as exc:
            logger.warning("quality judge failed for {}: {}", job.job_uid, exc)
            continue
        job.quality_verdict = parsed["verdict"]
        job.quality_confidence = float(parsed["confidence"])
        # Blend the read into the stored quality score (legitimacy + substance).
        job.quality_score = round((parsed["legit"] + parsed["substance"]) / 2.0, 1)
        job.quality_flags = list(dict.fromkeys((job.quality_flags or []) + parsed["flags"]))
        job.quality_model = model
        job.quality_checked_at = datetime.now(UTC)
        judged += 1
    session.commit()
    return judged
