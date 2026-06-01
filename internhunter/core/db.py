from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from internhunter.config.settings import get_settings
from internhunter.core.models import NormalizedJob


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Board(Base):
    __tablename__ = "boards"
    __table_args__ = (UniqueConstraint("ats", "token", name="uq_boards_ats_token"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ats: Mapped[str] = mapped_column(String, index=True)
    token: Mapped[str] = mapped_column(String, index=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    tier: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    board_url: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_polled: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_active: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("uq_jobs_url_hash", "url_hash", unique=True),
        Index("ix_jobs_dedupe", "company_slug", "title_normalized", "location_normalized"),
        Index("ix_jobs_posted_at", "posted_at"),
        Index("ix_jobs_deadline_at", "deadline_at"),
        Index("ix_jobs_is_internship", "is_internship"),
        Index("ix_jobs_discovery_score", "discovery_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int | None] = mapped_column(ForeignKey("boards.id"), nullable=True)

    job_uid: Mapped[str] = mapped_column(String, index=True)
    ats: Mapped[str] = mapped_column(String)
    board_token: Mapped[str] = mapped_column(String)
    source_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    canonical_url: Mapped[str] = mapped_column(String)
    url_hash: Mapped[str] = mapped_column(String)

    company: Mapped[str | None] = mapped_column(String, nullable=True)
    company_slug: Mapped[str] = mapped_column(String)
    company_domain: Mapped[str | None] = mapped_column(String, nullable=True)

    title: Mapped[str] = mapped_column(String)
    title_normalized: Mapped[str] = mapped_column(String)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    is_internship: Mapped[bool] = mapped_column(Boolean, default=False)
    internship_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    level_tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    location_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    location_normalized: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_scope: Mapped[str | None] = mapped_column(String, nullable=True)

    description_text: Mapped[str] = mapped_column(Text, default="")
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[list[str]] = mapped_column(JSON, default=list)

    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String, nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String, nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_rolling: Mapped[bool] = mapped_column(Boolean, default=False)

    sectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    times_seen_elsewhere: Mapped[int] = mapped_column(Integer, default=0)
    rarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    freshness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    discovery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("job_uid", "input_hash", name="uq_scores_job_input"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_uid: Mapped[str] = mapped_column(ForeignKey("jobs.job_uid"), index=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    input_hash: Mapped[str] = mapped_column(String)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_uid: Mapped[str] = mapped_column(ForeignKey("jobs.job_uid"), index=True)
    status: Mapped[str] = mapped_column(String, default="new")
    resume_path: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    method: Mapped[str] = mapped_column(String)
    ats: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    boards_found: Mapped[int] = mapped_column(Integer, default=0)
    boards_new: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="running")


_engine = None
_session_factory: sessionmaker[Session] | None = None


def _engine_url(db_path: Path | None) -> str:
    path = db_path or get_settings().db_path
    return f"sqlite:///{path}"


def init_db(db_path: Path | None = None) -> None:
    global _engine, _session_factory
    _engine = create_engine(_engine_url(db_path), future=True)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory()


_SCALAR_FIELDS = [
    "job_uid",
    "ats",
    "board_token",
    "source_job_id",
    "canonical_url",
    "url_hash",
    "company",
    "company_slug",
    "company_domain",
    "title",
    "title_normalized",
    "department",
    "employment_type",
    "is_internship",
    "internship_kind",
    "level_tags",
    "location_raw",
    "location_normalized",
    "country",
    "region",
    "city",
    "is_remote",
    "remote_scope",
    "description_text",
    "description_html",
    "requirements",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "posted_at",
    "updated_at",
    "deadline_at",
    "is_rolling",
    "sectors",
    "first_seen_at",
    "last_seen_at",
    "times_seen_elsewhere",
    "rarity_score",
    "freshness_score",
    "discovery_score",
    "embedding_id",
    "raw",
]


def upsert_jobs(
    session: Session,
    jobs: list[NormalizedJob],
    board: Board | None = None,
) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for job in jobs:
        existing = session.scalar(select(Job).where(Job.url_hash == job.url_hash))
        if existing is None:
            row = Job(**{field: getattr(job, field) for field in _SCALAR_FIELDS})
            if board is not None:
                row.board_id = board.id
            session.add(row)
            inserted += 1
        else:
            existing.last_seen_at = job.last_seen_at
            existing.updated_at = job.updated_at
            existing.times_seen_elsewhere = job.times_seen_elsewhere
            if job.discovery_score is not None:
                existing.discovery_score = job.discovery_score
            if board is not None:
                existing.board_id = board.id
            updated += 1
    session.commit()
    return inserted, updated
