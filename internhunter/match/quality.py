from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from internhunter.core.internship_filter import _SENIOR_RE

if TYPE_CHECKING:
    from internhunter.core.models import NormalizedJob

# Cheap, free, per-job slop signals. Each fires a flag and docks a soft penalty from a
# base of 100. NOTHING here drops a job — it only annotates a score + flags so the
# dashboard can rank/hide and the LLM judge can focus on the borderline.

_AGENCY_RE = re.compile(
    r"\b(our client|on behalf of (?:our|a) client|confidential client|staffing agency|"
    r"recruitment agency|recruiting firm|consultancy|we are a (?:staffing|recruiting))\b",
    re.IGNORECASE,
)
_MLM_SCAM_RE = re.compile(
    r"\b(commission[\s-]?only|unlimited earning|be your own boss|financial freedom|"
    r"no experience (?:needed|required|necessary)|pay a fee|registration fee|"
    r"starter kit|upfront (?:payment|fee)|earn \$?\d{3,}/(?:day|week))\b",
    re.IGNORECASE,
)
_CONTACT_CHANNEL_RE = re.compile(
    r"\b(whatsapp|telegram|signal)\b.{0,40}\b(only|us|me|apply|contact|message)\b",
    re.IGNORECASE,
)
_PERSONAL_EMAIL_RE = re.compile(
    r"\b[\w.+-]+@(gmail|yahoo|hotmail|outlook|protonmail)\.com\b", re.IGNORECASE
)
_GHOST_LANG_RE = re.compile(
    r"\b(always hiring|evergreen|general application|talent (?:community|pool|network)|"
    r"future openings|join our (?:talent|pipeline)|expression of interest|"
    r"we are always looking)\b",
    re.IGNORECASE,
)
_ENTRY_TITLE_RE = re.compile(r"\b(intern(?:ship)?|co[\s-]?op|new\s*grad|entry)\b", re.IGNORECASE)
_YEARS_EXP_RE = re.compile(
    r"\b(\d{1,2})\+?\s*years?(?:\s+of)?\s+(?:experience|exp)\b", re.IGNORECASE
)


@dataclass
class QualityHeuristic:
    score: float  # 0–100, higher = cleaner / more legit-looking
    flags: list[str] = field(default_factory=list)
    verdict_hint: str = "ok"  # ok | unclear | suspect


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def days_open(job: NormalizedJob, now: datetime | None = None) -> int:
    moment = now or datetime.now(tz=UTC)
    posted = _aware(job.posted_at)
    first_seen = _aware(job.first_seen_at)
    last = _aware(job.last_seen_at) or moment
    # A future posted_at is suspicious and must not silently zero-out the ghost
    # window: fall back to when we first saw the listing instead.
    if posted is not None and posted > last:
        start = first_seen
    else:
        start = posted or first_seen
    if start is None:
        return 0
    return max(0, (last - start).days)


def classify_quality(
    job: NormalizedJob,
    min_chars: int = 300,
    ghost_days: int = 45,
    now: datetime | None = None,
) -> QualityHeuristic:
    title = job.title or ""
    text = job.description_text or ""
    combined = f"{title}\n{text}"
    flags: list[str] = []
    score = 100.0

    # Trust weighting: free-text / aggregator sources are likelier to carry slop than a
    # company-owned ATS board.
    low_trust = job.ats in {"listing", "remotive", "jobicy", "arbeitnow", "themuse", "hackernews"}

    if len(text.strip()) < min_chars:
        flags.append("content_free")
        score -= 30 if low_trust else 20

    if _AGENCY_RE.search(combined):
        flags.append("agency")
        score -= 25

    scam = bool(_MLM_SCAM_RE.search(combined)) or bool(_CONTACT_CHANNEL_RE.search(combined))
    if scam:
        flags.append("mlm_scam")
        score -= 45
    if _PERSONAL_EMAIL_RE.search(text):
        flags.append("personal_email_apply")
        score -= 20 if low_trust else 8

    if _GHOST_LANG_RE.search(combined):
        flags.append("ghost_language")
        score -= 20

    opened = days_open(job, now)
    if opened > ghost_days:
        flags.append("ghost_duration")
        score -= min(25.0, 10.0 + (opened - ghost_days) / 6.0)

    # Intern/entry title that demands senior experience = incoherent (often a miscategorized
    # or farmed listing).
    if _ENTRY_TITLE_RE.search(title):
        years = _YEARS_EXP_RE.search(text)
        if (years and int(years.group(1)) >= 4) or _SENIOR_RE.search(title):
            flags.append("requirement_incoherence")
            score -= 15

    # is_rolling is surfaced but weighted near zero: internships legitimately use rolling
    # admission, so it must NOT push good niche roles toward "slop".
    if job.is_rolling:
        flags.append("rolling")
        score -= 2

    score = max(0.0, min(100.0, score))

    if "mlm_scam" in flags or ("agency" in flags and "content_free" in flags):
        verdict_hint = "suspect"
    elif flags and flags != ["rolling"]:
        verdict_hint = "unclear"
    else:
        verdict_hint = "ok"

    return QualityHeuristic(score=score, flags=flags, verdict_hint=verdict_hint)
