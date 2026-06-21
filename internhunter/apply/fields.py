from __future__ import annotations

import re
from dataclasses import dataclass, field

from internhunter.apply.applicant import Applicant


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    ftype: str
    required: bool
    options: tuple[str, ...] = field(default=())


# canonical key -> substrings that identify it (checked against a normalized label)
_LABEL_PATTERNS: dict[str, tuple[str, ...]] = {
    "full_name": ("full name", "name"),
    "email": ("email", "e-mail"),
    "phone": ("phone", "mobile", "telephone"),
    "linkedin_url": ("linkedin",),
    "github_url": ("github",),
    "portfolio_url": ("portfolio", "website", "personal site"),
    "school": ("school", "university", "college"),
    "location": ("location", "city"),
}


def _normalize(label: str) -> str:
    return re.sub(r"\s+", " ", label or "").strip().lower()


def field_key(label: str) -> str | None:
    norm = _normalize(label)
    # longest, most specific patterns first so "full name" wins over bare "name"
    for key, subs in _LABEL_PATTERNS.items():
        for sub in subs:
            if sub in norm:
                return key
    return None


def _is_resume_upload(f: FormField) -> bool:
    return f.ftype == "file" and any(w in _normalize(f.label) for w in ("resume", "cv"))


def classify_fields(
    spec_fields: list[FormField], a: Applicant
) -> tuple[dict[str, str], list[FormField]]:
    payload: dict[str, str] = {}
    unknown: list[FormField] = []
    for f in spec_fields:
        if _is_resume_upload(f):
            payload[f.name] = "@resume"
            continue
        key = field_key(f.label)
        value = str(getattr(a, key) or "").strip() if key else ""
        if value:
            payload[f.name] = value
        elif f.required:
            unknown.append(f)
    return payload, unknown
