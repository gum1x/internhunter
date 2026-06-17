from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from internhunter.sources.base import BoardRef

_RESERVED_TOKENS = {
    "embed",
    "job_board",
    "jobs",
    "postings",
    "posting-api",
    "api",
    "v0",
    "v1",
    "boards",
    "job-board",
    "companies",
    "accounts",
    "careers",
    "o",
    "j",
    "search",
    "apply",
}

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,62}$")


@dataclass(frozen=True)
class Detection:
    ats: str
    token: str
    source_url: str


def _valid_token(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip().strip("/")
    if not token or token.lower() in _RESERVED_TOKENS:
        return None
    if not _TOKEN_RE.match(token):
        return None
    return token


def _path_parts(path: str) -> list[str]:
    return [p for p in path.split("/") if p]


def _detect_greenhouse(host: str, parts: list[str], query: dict[str, list[str]]) -> str | None:
    if "greenhouse.io" not in host:
        return None
    if "for" in query:
        return _valid_token(query["for"][0])
    if host.startswith("boards-api") and len(parts) >= 2 and parts[0] == "v1":
        return None
    if parts and parts[0] in {"embed", "v1"}:
        parts = parts[1:]
    if parts and parts[0] == "boards":
        parts = parts[1:]
    return _valid_token(parts[0]) if parts else None


def _detect_lever(host: str, parts: list[str]) -> str | None:
    if "lever.co" not in host:
        return None
    if host.startswith("api.lever.co") and len(parts) >= 2 and parts[0] in {"v0", "v1"}:
        parts = parts[2:]
    return _valid_token(parts[0]) if parts else None


def _detect_ashby(host: str, parts: list[str]) -> str | None:
    if "ashbyhq.com" not in host:
        return None
    if host.startswith("api.ashbyhq.com"):
        if "job-board" in parts:
            idx = parts.index("job-board")
            return _valid_token(parts[idx + 1]) if idx + 1 < len(parts) else None
        return None
    return _valid_token(parts[0]) if parts else None


def _detect_smartrecruiters(host: str, parts: list[str]) -> str | None:
    if "smartrecruiters.com" not in host:
        return None
    if host.startswith("api.smartrecruiters.com"):
        if "companies" in parts:
            idx = parts.index("companies")
            return _valid_token(parts[idx + 1]) if idx + 1 < len(parts) else None
        return None
    return _valid_token(parts[0]) if parts else None


def _detect_workable(host: str, parts: list[str]) -> str | None:
    if "workable.com" not in host:
        return None
    if host.startswith("apply.workable.com"):
        return _valid_token(parts[0]) if parts else None
    if host.startswith("www.workable.com") or host.startswith("workable.com"):
        if "accounts" in parts:
            idx = parts.index("accounts")
            return _valid_token(parts[idx + 1]) if idx + 1 < len(parts) else None
        return None
    sub = host.split(".workable.com")[0]
    return _valid_token(sub)


def _detect_subdomain(host: str, suffix: str, ats_label: str) -> str | None:
    if not host.endswith(suffix):
        return None
    sub = host[: -len(suffix)]
    sub = sub.split(".")[-1] if sub else sub
    return _valid_token(sub)


def _detect_path_token(host: str, parts: list[str], host_match: str, segment: str) -> str | None:
    if host != host_match and not host.endswith(f".{host_match}"):
        return None
    if segment in parts:
        idx = parts.index(segment)
        return _valid_token(parts[idx + 1]) if idx + 1 < len(parts) else None
    return None


_SUBDOMAIN_ATS = (
    (".recruitee.com", "recruitee"),
    (".jobs.personio.de", "personio"),
    (".jobs.personio.com", "personio"),
    (".breezy.hr", "breezy"),
    (".applytojob.com", "jazzhr"),
    (".bamboohr.com", "bamboohr"),
    (".rippling-ats.com", "rippling"),
    (".zohorecruit.com", "zohorecruit"),
    (".pinpointhq.com", "pinpoint"),
    # api.teamtailor.com -> "api" is in _RESERVED_TOKENS, so it is excluded by _valid_token
    (".teamtailor.com", "teamtailor"),
)

_PATH_ATS = (
    ("jobs.jobvite.com", "careers", "jobvite"),
    ("jobs.dover.com", "companies", "dover"),
    ("careers.icims.com", "jobs", "icims"),
    ("jobs.adp.com", "company", "adp"),
    # comeet boards: www.comeet.com/jobs/{company-slug}/{uid}; company-slug is the stable token
    ("www.comeet.com", "jobs", "comeet"),
    ("www.comeet.co", "jobs", "comeet"),
)

_PATH_FIRST_ATS = (
    ("recruiting.ultipro.com", "ultipro"),
    ("recruiting.paylocity.com", "paylocity"),
)


def _detect_workday(host: str, parts: list[str]) -> str | None:
    if not host.endswith(".myworkdayjobs.com"):
        return None
    tenant = host.split(".")[0]
    return _valid_token(tenant)


def _detect_path_first(host: str, parts: list[str], host_match: str) -> str | None:
    if host != host_match and not host.endswith(f".{host_match}"):
        return None
    return _valid_token(parts[0]) if parts else None


def detect_from_url(url: str) -> Detection | None:
    parts_url = urlsplit(url if "//" in url else f"https://{url}")
    host = parts_url.netloc.lower()
    if not host:
        return None
    path_parts = _path_parts(parts_url.path)
    query = parse_qs(parts_url.query)

    token = _detect_greenhouse(host, path_parts, query)
    if token:
        return Detection("greenhouse", token, url)
    token = _detect_lever(host, path_parts)
    if token:
        return Detection("lever", token, url)
    token = _detect_ashby(host, path_parts)
    if token:
        return Detection("ashby", token, url)
    token = _detect_smartrecruiters(host, path_parts)
    if token:
        return Detection("smartrecruiters", token, url)
    token = _detect_workable(host, path_parts)
    if token:
        return Detection("workable", token, url)
    token = _detect_workday(host, path_parts)
    if token:
        return Detection("workday", token, url)

    for host_match, segment, ats_label in _PATH_ATS:
        token = _detect_path_token(host, path_parts, host_match, segment)
        if token:
            return Detection(ats_label, token, url)

    for host_match, ats_label in _PATH_FIRST_ATS:
        token = _detect_path_first(host, path_parts, host_match)
        if token:
            return Detection(ats_label, token, url)

    token = _detect_subdomain(host, ".fa.oraclecloud.com", "oracle_cloud")
    if token:
        return Detection("oracle_cloud", token, url)

    for suffix, ats_label in _SUBDOMAIN_ATS:
        token = _detect_subdomain(host, suffix, ats_label)
        if token:
            return Detection(ats_label, token, url)
    return None


_URL_IN_HTML_RE = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)


def detect_from_html(markup: str) -> list[Detection]:
    seen: set[tuple[str, str]] = set()
    found: list[Detection] = []
    unescaped = html.unescape(markup)
    for match in _URL_IN_HTML_RE.finditer(unescaped):
        detection = detect_from_url(match.group(0))
        if detection is None:
            continue
        key = (detection.ats, detection.token)
        if key in seen:
            continue
        seen.add(key)
        found.append(detection)
    return found


def detection_to_board_ref(detection: Detection, company: str | None = None) -> BoardRef:
    return BoardRef(ats=detection.ats, token=detection.token, company=company)
