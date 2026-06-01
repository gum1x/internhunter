from __future__ import annotations

import re
from dataclasses import dataclass, field

_KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("co-op", re.compile(r"\bco[\s\-]?op\b", re.IGNORECASE)),
    ("summer-analyst", re.compile(r"\bsummer\s+analyst\b", re.IGNORECASE)),
    ("rotational", re.compile(r"\brotational\b|\brotation(?:al)?\s+program\b", re.IGNORECASE)),
    ("apprentice", re.compile(r"\bapprentice(?:ship)?\b", re.IGNORECASE)),
    ("new-grad", re.compile(r"\bnew\s*grad(?:uate)?\b", re.IGNORECASE)),
    (
        "university-program",
        re.compile(r"\buniversity\s+(?:program|graduate|hire|recruit)", re.IGNORECASE),
    ),
    ("campus", re.compile(r"\bcampus\b|\bon[\s\-]?campus\b", re.IGNORECASE)),
    ("early-career", re.compile(r"\bearly[\s\-]?career\b|\bentry[\s\-]?level\b", re.IGNORECASE)),
    ("intern", re.compile(r"\bintern(?:ship)?\b", re.IGNORECASE)),
]

_INTERNSHIP_RE = re.compile(
    r"\bintern(?:ship)?\b|\bco[\s\-]?op\b|\bsummer\s+analyst\b|\bapprentice(?:ship)?\b|"
    r"\bnew\s*grad(?:uate)?\b|\bearly[\s\-]?career\b|\bcampus\b|\brotational\b|"
    r"\buniversity\s+(?:program|graduate|hire|recruit)|\bplacement\b|\bworking\s+student\b|"
    r"\bgraduate\s+(?:program|scheme|trainee)\b",
    re.IGNORECASE,
)

_STRONG_TITLE_RE = re.compile(
    r"\bintern(?:ship)?\b|\bco[\s\-]?op\b|\bsummer\s+analyst\b|\bapprentice(?:ship)?\b|"
    r"\bworking\s+student\b",
    re.IGNORECASE,
)

_STRONG_DESC_RE = re.compile(
    r"\bsummer\s+intern(?:ship)?\b|\bintern(?:ship)?\s+program\b|"
    r"\bintern(?:ship)?\s+(?:position|role|opportunity)\b|\bco[\s\-]?op\s+program\b|"
    r"\bis\s+an?\s+intern(?:ship)?\b",
    re.IGNORECASE,
)

_SENIOR_RE = re.compile(
    r"\b(senior|sr|staff|principal|lead|manager|director|head\s+of|vp|vice\s+president|"
    r"architect|chief|ii|iii|iv)\b",
    re.IGNORECASE,
)

_LEVEL_TAG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("summer", re.compile(r"\bsummer\b", re.IGNORECASE)),
    ("fall", re.compile(r"\bfall\b|\bautumn\b", re.IGNORECASE)),
    ("spring", re.compile(r"\bspring\b", re.IGNORECASE)),
    ("winter", re.compile(r"\bwinter\b", re.IGNORECASE)),
    ("phd", re.compile(r"\bph\.?d\b|\bdoctoral\b", re.IGNORECASE)),
    ("masters", re.compile(r"\bmaster'?s?\b|\bmsc\b|\bm\.?s\.?\b", re.IGNORECASE)),
    ("undergrad", re.compile(r"\bundergrad(?:uate)?\b|\bbachelor'?s?\b|\bbsc\b", re.IGNORECASE)),
    ("entry-level", re.compile(r"\bentry[\s\-]?level\b", re.IGNORECASE)),
    ("paid", re.compile(r"\bpaid\b", re.IGNORECASE)),
    ("part-time", re.compile(r"\bpart[\s\-]?time\b", re.IGNORECASE)),
    ("full-time", re.compile(r"\bfull[\s\-]?time\b", re.IGNORECASE)),
    ("remote", re.compile(r"\bremote\b", re.IGNORECASE)),
]


@dataclass
class InternshipClassification:
    is_internship: bool
    kind: str | None = None
    level_tags: list[str] = field(default_factory=list)


def classify_internship(title: str, text: str = "") -> InternshipClassification:
    combined = f"{title}\n{text}"
    senior = bool(_SENIOR_RE.search(title))

    if _STRONG_TITLE_RE.search(title):
        is_internship = True
    elif _INTERNSHIP_RE.search(title):
        is_internship = not senior
    else:
        is_internship = bool(_STRONG_DESC_RE.search(text)) and not senior

    kind: str | None = None
    if is_internship:
        for label, pattern in _KIND_PATTERNS:
            if pattern.search(title):
                kind = label
                break
        if kind is None:
            for label, pattern in _KIND_PATTERNS:
                if pattern.search(combined):
                    kind = label
                    break

    level_tags = [label for label, pattern in _LEVEL_TAG_PATTERNS if pattern.search(combined)]

    return InternshipClassification(
        is_internship=is_internship,
        kind=kind,
        level_tags=level_tags,
    )
