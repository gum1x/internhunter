"""Target-firm + keyword filter layer.

Loads the single user-editable ``targets.yaml`` and evaluates jobs against it. This is
the noise gate for the alert pipeline: only jobs that match a target firm or a watched
keyword (and clear the exclude veto + location gate) get pushed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from internhunter.core.db import Job
from internhunter.core.normalize import canonical_company_slug, normalize_company_slug


@dataclass(frozen=True)
class TargetFirm:
    name: str
    slug: str
    canonical_slug: str
    domains: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    priority: str = "normal"


@dataclass(frozen=True)
class TargetConfig:
    enabled: bool = True
    firms: tuple[TargetFirm, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    seniority: tuple[str, ...] = ("intern",)
    locations: tuple[str, ...] = ()
    remote_ok: bool = True
    funding_stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetMatch:
    matched: bool
    firm: TargetFirm | None = None
    reasons: tuple[str, ...] = ()

    @property
    def is_target_firm(self) -> bool:
        return self.firm is not None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item).strip())


def _parse_firm(raw: dict[str, Any]) -> TargetFirm | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    return TargetFirm(
        name=name,
        slug=normalize_company_slug(name),
        canonical_slug=canonical_company_slug(name),
        domains=tuple(
            d.lower().removeprefix("www.") for d in _as_str_tuple(raw.get("domains"))
        ),
        tags=_as_str_tuple(raw.get("tags")),
        priority=str(raw.get("priority") or "normal"),
    )


def load_targets(path: Path | str) -> TargetConfig:
    """Parse targets.yaml. Missing file or empty/malformed sections degrade to an
    empty config (matcher then falls back to score-only alerting) instead of crashing
    the scheduled pipeline."""
    p = Path(path)
    if not p.exists():
        return TargetConfig(enabled=False)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return TargetConfig(enabled=False)
    firms = []
    for raw in data.get("firms") or []:
        if isinstance(raw, dict):
            firm = _parse_firm(raw)
            if firm is not None:
                firms.append(firm)
    keywords = data.get("keywords") or {}
    if not isinstance(keywords, dict):
        keywords = {}
    return TargetConfig(
        enabled=bool(data.get("enabled", True)),
        firms=tuple(firms),
        include_keywords=tuple(
            k.lower() for k in _as_str_tuple(keywords.get("include"))
        ),
        exclude_keywords=tuple(
            k.lower() for k in _as_str_tuple(keywords.get("exclude"))
        ),
        seniority=_as_str_tuple(data.get("seniority")) or ("intern",),
        locations=tuple(loc.lower() for loc in _as_str_tuple(data.get("locations"))),
        remote_ok=bool(data.get("remote_ok", True)),
        funding_stages=_as_str_tuple(data.get("funding_stages")),
    )


@lru_cache(maxsize=4)
def _cached_targets(path: str, mtime: float) -> TargetConfig:
    return load_targets(path)


def get_targets(path: Path | str) -> TargetConfig:
    """mtime-keyed cache: edits to targets.yaml take effect on the next run without a
    restart, while steady-state scheduled runs skip re-parsing."""
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _cached_targets(str(p), mtime)


def _firm_for_job(job: Job, config: TargetConfig) -> TargetFirm | None:
    slug = (job.company_slug or "").lower()
    canonical = canonical_company_slug(job.company)
    domain = (job.company_domain or "").lower().removeprefix("www.")
    for firm in config.firms:
        if domain and firm.domains and any(
            domain == d or domain.endswith("." + d) for d in firm.domains
        ):
            return firm
        if slug and slug == firm.slug:
            return firm
        if canonical and canonical == firm.canonical_slug:
            return firm
    return None


def _location_ok(job: Job, config: TargetConfig) -> bool:
    if job.is_remote and config.remote_ok:
        return True
    if not config.locations:
        return True
    location = (job.location_normalized or job.location_raw or "").lower()
    return any(loc in location for loc in config.locations)


def evaluate_job(job: Job, config: TargetConfig) -> TargetMatch:
    """One job against the whole filter layer. Order matters: exclude veto first, then
    location gate, then firm/keyword matching."""
    if not config.enabled:
        return TargetMatch(matched=False)
    title = (job.title or "").lower()
    for word in config.exclude_keywords:
        if word in title:
            return TargetMatch(matched=False, reasons=(f"excluded:{word.strip()}",))
    if not _location_ok(job, config):
        return TargetMatch(matched=False, reasons=("location",))

    reasons: list[str] = []
    firm = _firm_for_job(job, config)
    keyword_hit = next((k for k in config.include_keywords if k in title), None)
    role_ok = bool(job.is_internship) or keyword_hit is not None
    if firm is not None and role_ok:
        reasons.append(f"target-firm:{firm.name}")
        if keyword_hit:
            reasons.append(f"keyword:{keyword_hit}")
        return TargetMatch(matched=True, firm=firm, reasons=tuple(reasons))
    if keyword_hit is not None:
        return TargetMatch(matched=True, reasons=(f"keyword:{keyword_hit}",))
    return TargetMatch(matched=False)
