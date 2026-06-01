from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EmploymentType(StrEnum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    internship = "internship"
    temporary = "temporary"
    other = "other"


class InternshipKind(StrEnum):
    intern = "intern"
    co_op = "co-op"
    summer_analyst = "summer-analyst"
    university_program = "university-program"
    campus = "campus"
    early_career = "early-career"
    new_grad = "new-grad"
    apprentice = "apprentice"
    rotational = "rotational"


class RemoteScope(StrEnum):
    fully_remote = "fully_remote"
    hybrid = "hybrid"
    remote_within_country = "remote_within_country"
    remote_anywhere = "remote_anywhere"


class NormalizedJob(BaseModel):
    job_uid: str
    ats: str
    board_token: str
    source_job_id: str | None = None
    canonical_url: str
    url_hash: str

    company: str | None = None
    company_slug: str
    company_domain: str | None = None

    title: str
    title_normalized: str
    department: str | None = None
    employment_type: str | None = None
    is_internship: bool = False
    internship_kind: str | None = None
    level_tags: list[str] = Field(default_factory=list)

    location_raw: str | None = None
    location_normalized: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    is_remote: bool = False
    remote_scope: str | None = None

    description_text: str = ""
    description_html: str | None = None
    requirements: list[str] = Field(default_factory=list)

    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None

    posted_at: datetime | None = None
    updated_at: datetime | None = None
    deadline_at: datetime | None = None
    is_rolling: bool = False

    sectors: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: datetime
    times_seen_elsewhere: int = 0
    rarity_score: float | None = None
    freshness_score: float | None = None
    discovery_score: float | None = None
    embedding_id: int | None = None

    raw: dict[str, Any] = Field(default_factory=dict)
