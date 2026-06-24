from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from internhunter.config.settings import Settings, get_settings

REQUIRED_FIELDS: tuple[str, ...] = ("full_name", "email", "phone", "work_authorization")


@dataclass(frozen=True)
class Applicant:
    full_name: str
    email: str
    phone: str
    work_authorization: str
    requires_sponsorship: bool
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    school: str = ""
    grad_date: str = ""


def load_applicant(settings: Settings | None = None) -> Applicant:
    import yaml

    resolved = settings or get_settings()
    data = yaml.safe_load(resolved.profile_path.read_text(encoding="utf-8")) or {}
    block = data.get("applicant") or {}
    known = {f.name for f in fields(Applicant)}
    kwargs: dict[str, Any] = {k: (block.get(k) or "") for k in known}
    kwargs["requires_sponsorship"] = bool(block.get("requires_sponsorship", False))
    return Applicant(**kwargs)


def validate_applicant(a: Applicant) -> list[str]:
    return [name for name in REQUIRED_FIELDS if not str(getattr(a, name)).strip()]
