from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

_WHITESPACE_RE = re.compile(r"\s+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9 ]+")

_REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|distributed|anywhere|telecommute)\b", re.IGNORECASE
)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_REMOTE_ANYWHERE_RE = re.compile(r"\b(anywhere|global|worldwide)\b", re.IGNORECASE)

_ROLLING_RE = re.compile(
    r"\b(rolling basis|reviewed on a rolling|applications? (are )?reviewed as|until filled|"
    r"open until filled|no (fixed |set )?deadline)\b",
    re.IGNORECASE,
)

_MONTH = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DATE_FRAGMENT = (
    rf"(?:(?:{_MONTH})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s*\d{{4}})?"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH})(?:,?\s*\d{{4}})?"
    rf"|\d{{4}}-\d{{1,2}}-\d{{1,2}}"
    rf"|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}})"
)
_DEADLINE_RE = re.compile(
    r"(?:apply by|application deadline|applications? close(?:s)?(?: on)?|"
    r"deadline(?: is| to apply)?|"
    r"closing date|last date to apply|apply before)\s*[:\-]?\s*"
    rf"({_DATE_FRAGMENT})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocationResult:
    city: str | None
    region: str | None
    country: str | None
    normalized: str | None
    is_remote: bool
    remote_scope: str | None


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def normalize_company_slug(name: str | None) -> str:
    if not name:
        return ""
    slug = _SLUG_STRIP_RE.sub("-", name.strip().lower())
    return slug.strip("-")


_CORP_SUFFIXES = (
    "inc", "llc", "l-l-c", "corp", "corporation", "co", "ltd", "limited",
    "lp", "llp", "plc", "gmbh", "ag", "sa", "srl", "bv", "nv", "pte", "pvt",
    "holdings", "group", "technologies", "technology", "labs", "the",
)


def canonical_company_slug(name: str | None) -> str:
    """A suffix-stripped slug for JOINING records that name the same company differently
    (e.g. job 'google' vs filing 'Google LLC'). Drops common corporate suffixes/fillers and
    collapses hyphens so both sides land on the same key."""
    slug = normalize_company_slug(name)
    if not slug:
        return ""
    tokens = [t for t in slug.split("-") if t and t not in _CORP_SUFFIXES]
    return "".join(tokens)



def normalize_title(title: str) -> str:
    lowered = title.strip().lower()
    lowered = _NON_ALNUM_SPACE_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", lowered).strip()


def normalize_location(raw: str | None) -> LocationResult:
    if not raw or not raw.strip():
        return LocationResult(None, None, None, None, False, None)

    value = _WHITESPACE_RE.sub(" ", raw.strip())
    is_remote = bool(_REMOTE_RE.search(value))
    remote_scope: str | None = None
    if is_remote:
        if _HYBRID_RE.search(value):
            remote_scope = "hybrid"
        elif _REMOTE_ANYWHERE_RE.search(value):
            remote_scope = "remote_anywhere"
        else:
            remote_scope = "fully_remote"
    elif _HYBRID_RE.search(value):
        remote_scope = "hybrid"

    parts = [p.strip() for p in re.split(r"[,/|]", value) if p.strip()]
    city: str | None = None
    region: str | None = None
    country: str | None = None
    if len(parts) == 1:
        city = parts[0]
    elif len(parts) == 2:
        city, region = parts[0], parts[1]
    elif len(parts) >= 3:
        city, region, country = parts[0], parts[1], parts[2]

    return LocationResult(
        city=city,
        region=region,
        country=country,
        normalized=value,
        is_remote=is_remote,
        remote_scope=remote_scope,
    )


def parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1_000_000_000_000:
            seconds = seconds / 1000.0
        # Hostile/garbage epoch values (e.g. 1e20, a 40-digit string) overflow
        # fromtimestamp; treat them as "no date" rather than crashing the ingest channel.
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return parse_datetime(int(text))
        try:
            parsed = dateutil_parser.parse(text)
        except (ValueError, OverflowError, dateutil_parser.ParserError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def make_url_hash(url: str) -> str:
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()


def make_job_uid(ats: str, token: str, source_job_id: str | None, url: str) -> str:
    key = "|".join([ats, token, source_job_id or "", url.strip()])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def is_rolling(text: str) -> bool:
    if not text:
        return False
    return bool(_ROLLING_RE.search(text))


def extract_deadline(text: str) -> datetime | None:
    if not text:
        return None
    for match in _DEADLINE_RE.finditer(text):
        candidate = match.group(1).strip().rstrip(".,")
        parsed = parse_datetime(candidate)
        if parsed is not None:
            return parsed
    return None
