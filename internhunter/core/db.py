from __future__ import annotations

import hashlib
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
    event,
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
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
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

    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    quality_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_model: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("job_uid", "input_hash", name="uq_scores_job_input"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_uid: Mapped[str] = mapped_column(ForeignKey("jobs.job_uid"), index=True)
    # NOTE: scale is model-specific — "prefilter:*" rows store 0-1 (embedding cosine),
    # "llm:*" rows store 0-100. Consumers MUST filter by `model` before reading/sorting
    # this column so the two scales are never compared. (See web/app.py, which scopes to
    # "llm:%".)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    input_hash: Mapped[str] = mapped_column(String)


class Application(Base):
    """A job the user is tracking. Display fields are snapshotted at add-time so the
    tracker/CSV is self-contained; job_uid stays for dedupe + the 'tracked?' badge."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_uid", name="uq_applications_job_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_uid: Mapped[str] = mapped_column(ForeignKey("jobs.job_uid"))
    status: Mapped[str] = mapped_column(String, default="To Apply")
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    company_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    emailed: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resume_path: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
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


class OfficerLead(Base):
    """A person name surfaced by a discovery channel (e.g. SEC Form D officers) before
    the contacts pipeline runs — a free people-lead that the enrichment funnel reads."""

    __tablename__ = "officer_leads"
    __table_args__ = (
        UniqueConstraint("company_slug", "full_name", name="uq_officer_company_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_slug: Mapped[str] = mapped_column(String, index=True)
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    full_name: Mapped[str] = mapped_column(String)
    role_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="edgar")
    filed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Sighting(Base):
    __tablename__ = "sightings"
    __table_args__ = (UniqueConstraint("job_uid", name="uq_sightings_job_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_uid: Mapped[str] = mapped_column(String, index=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_present: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    poll_count: Mapped[int] = mapped_column(Integer, default=1)
    reappearances: Mapped[int] = mapped_column(Integer, default=0)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("company_slug", name="uq_companies_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_slug: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    email_pattern: Mapped[str | None] = mapped_column(String, nullable=True)
    email_pattern_conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    domain_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_catch_all: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_org: Mapped[str | None] = mapped_column(String, nullable=True)
    headcount_band: Mapped[str | None] = mapped_column(String, nullable=True)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    notes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("company_slug", "email", name="uq_contacts_company_email"),
        Index("ix_contacts_role_category", "role_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_slug: Mapped[str] = mapped_column(String, index=True)
    company_domain: Mapped[str | None] = mapped_column(String, nullable=True)

    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    role_category: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[float | None] = mapped_column(Float, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_login: Mapped[str | None] = mapped_column(String, nullable=True)

    email: Mapped[str | None] = mapped_column(String, nullable=True)
    email_status: Mapped[str] = mapped_column(String, default="guessed")
    email_source: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    person_source: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# Channel kinds a person can be reached on (fixed set; Contact.email stays the best-work
# anchor). Auto-created via create_all — no migration entry needed.
CHANNEL_KINDS = (
    "work_email", "personal_email", "linkedin", "x", "mastodon", "bluesky", "github", "site",
)


class ContactChannel(Base):
    __tablename__ = "contact_channels"
    __table_args__ = (
        UniqueConstraint("contact_id", "kind", "value_norm", name="uq_channel_contact_kind_value"),
        Index("ix_channel_kind_valuenorm", "kind", "value_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)
    value_norm: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="guessed")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


def norm_channel_value(value: str) -> str:
    return value.strip().lower().rstrip("/")


_engine = None
_session_factory: sessionmaker[Session] | None = None


def _engine_url(db_path: Path | None) -> str:
    path = db_path or get_settings().db_path
    return f"sqlite:///{path}"


# New columns added to pre-existing tables. create_all() only CREATES tables (new
# ones like `sightings` are made automatically); it never ALTERs, so columns added
# to `jobs`/`companies` after a DB already exists must be backfilled here. Idempotent.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "jobs": [
        ("quality_score", "FLOAT"),
        ("quality_verdict", "VARCHAR"),
        ("quality_flags", "JSON"),
        ("quality_confidence", "FLOAT"),
        ("quality_model", "VARCHAR"),
        ("quality_checked_at", "DATETIME"),
    ],
    "companies": [
        ("domain_confidence", "FLOAT"),
    ],
    "applications": [
        ("company", "VARCHAR"),
        ("company_slug", "VARCHAR"),
        ("role", "VARCHAR"),
        ("location", "VARCHAR"),
        ("link", "VARCHAR"),
        ("due_date", "DATETIME"),
        ("emailed", "BOOLEAN"),
        ("contact_name", "VARCHAR"),
        ("contact_email", "VARCHAR"),
        ("applied_at", "DATETIME"),
        ("created_at", "DATETIME"),
    ],
}

# Unique indexes to enforce on pre-existing tables. create_all() emits a table's
# UniqueConstraint only when it CREATEs the table; for a table that already exists we must
# add it by hand. CREATE UNIQUE INDEX IF NOT EXISTS is idempotent (safe if the column is
# already empty/unique, as the live `applications` table is).
_UNIQUE_INDEXES: dict[str, list[tuple[str, str]]] = {
    "applications": [("uq_applications_job_uid", "job_uid")],
}


def _migrate(engine: Any) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all already made it with all columns
            have = {col["name"] for col in inspector.get_columns(table)}
            for name, sql_type in columns:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
        for table, indexes in _UNIQUE_INDEXES.items():
            if table not in existing_tables:
                continue  # create_all will emit the constraint when it creates the table
            for index_name, column in indexes:
                conn.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                        f"ON {table} ({column})"
                    )
                )


def _sqlite_on_connect(dbapi_conn: Any, _record: Any) -> None:
    """WAL lets the dashboard's user-triggered writes (tracker add/edit) and reads run
    concurrently with the scoring/discovery writers instead of failing on a locked DB."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=NORMAL")  # safe under WAL; faster commits = shorter lock holds
    cur.close()


def init_db(db_path: Path | None = None) -> None:
    global _engine, _session_factory
    _engine = create_engine(
        _engine_url(db_path), future=True, connect_args={"timeout": 30}
    )
    event.listen(_engine, "connect", _sqlite_on_connect)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    _migrate(_engine)  # add columns to pre-existing tables BEFORE create_all
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
    "quality_score",
    "quality_verdict",
    "quality_flags",
    "quality_confidence",
    "quality_model",
    "quality_checked_at",
    "raw",
]


def _content_fingerprint(job: NormalizedJob) -> str:
    raw = f"{job.title_normalized}\n{(job.description_text or '')[:2000]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _record_sighting(session: Session, job: NormalizedJob) -> None:
    fp = _content_fingerprint(job)
    row = session.scalar(select(Sighting).where(Sighting.job_uid == job.job_uid))
    now = _utcnow()
    if row is None:
        session.add(
            Sighting(
                job_uid=job.job_uid,
                content_fingerprint=fp,
                first_seen=now,
                last_present=now,
                poll_count=1,
            )
        )
        return
    row.poll_count += 1
    # A gap before reappearing (>7 days since last seen) with unchanged text is the
    # canonical evergreen/ghost signal.
    last = row.last_present
    if last is not None:
        last = last if last.tzinfo is not None else last.replace(tzinfo=UTC)
        if (now - last).days >= 7 and row.content_fingerprint == fp:
            row.reappearances += 1
    row.last_present = now
    row.content_fingerprint = fp


def _annotate_quality(job: NormalizedJob) -> None:
    """Cheap heuristic quality pass at write time (LLM verdict is layered on later)."""
    from internhunter.match.quality import classify_quality

    result = classify_quality(job)
    job.quality_score = result.score
    job.quality_flags = result.flags


def upsert_jobs(
    session: Session,
    jobs: list[NormalizedJob],
    board: Board | None = None,
) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for job in jobs:
        _annotate_quality(job)
        _record_sighting(session, job)
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
            existing.quality_score = job.quality_score
            existing.quality_flags = job.quality_flags
            if board is not None:
                existing.board_id = board.id
            updated += 1
    session.commit()
    return inserted, updated


_CONTACT_FIELDS = [
    "company_slug",
    "company_domain",
    "full_name",
    "title",
    "role_category",
    "priority",
    "linkedin_url",
    "github_login",
    "email",
    "email_status",
    "email_source",
    "confidence",
    "label",
    "person_source",
    "evidence",
]


def _find_existing_contact(session: Session, contact: Contact) -> Contact | None:
    if contact.email:
        match = session.scalar(
            select(Contact).where(
                Contact.company_slug == contact.company_slug,
                Contact.email == contact.email,
            )
        )
        if match is not None:
            return match
    if contact.linkedin_url:
        return session.scalar(
            select(Contact).where(
                Contact.company_slug == contact.company_slug,
                Contact.linkedin_url == contact.linkedin_url,
            )
        )
    if contact.full_name:
        return session.scalar(
            select(Contact).where(
                Contact.company_slug == contact.company_slug,
                Contact.full_name == contact.full_name,
                Contact.email.is_(None),
            )
        )
    return None


def upsert_contact(session: Session, contact: Contact) -> tuple[Contact, bool]:
    """Insert-or-update one contact; returns (persisted_row, was_inserted). The row is
    flushed so its id is available for attaching ContactChannel rows. Does not commit."""
    existing = _find_existing_contact(session, contact)
    if existing is None:
        session.add(contact)
        session.flush()
        return contact, True
    for field in _CONTACT_FIELDS:
        value = getattr(contact, field)
        if value is not None and value != "":
            setattr(existing, field, value)
    existing.last_seen_at = _utcnow()
    return existing, False


def upsert_contacts(session: Session, contacts: list[Contact]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for contact in contacts:
        _row, was_inserted = upsert_contact(session, contact)
        inserted += int(was_inserted)
        updated += int(not was_inserted)
    session.commit()
    return inserted, updated


def upsert_channels(
    session: Session, contact_id: int, channels: list[ContactChannel]
) -> int:
    """Idempotent per-channel upsert keyed on (contact_id, kind, value_norm). Updates the
    row only when the new confidence is higher. Does not commit."""
    inserted = 0
    for ch in channels:
        ch.contact_id = contact_id
        ch.value_norm = norm_channel_value(ch.value)
        existing = session.scalar(
            select(ContactChannel).where(
                ContactChannel.contact_id == contact_id,
                ContactChannel.kind == ch.kind,
                ContactChannel.value_norm == ch.value_norm,
            )
        )
        if existing is None:
            session.add(ch)
            inserted += 1
            continue
        existing.last_seen_at = _utcnow()
        if (ch.confidence or 0.0) >= (existing.confidence or 0.0):
            existing.confidence = ch.confidence
            existing.label = ch.label
            existing.status = ch.status
            existing.verified = ch.verified or existing.verified
            existing.source = ch.source or existing.source
            if ch.evidence:
                existing.evidence = {**(existing.evidence or {}), **ch.evidence}
    return inserted


def upsert_officer_leads(session: Session, leads: list[OfficerLead]) -> int:
    inserted = 0
    for lead in leads:
        existing = session.scalar(
            select(OfficerLead).where(
                OfficerLead.company_slug == lead.company_slug,
                OfficerLead.full_name == lead.full_name,
            )
        )
        if existing is None:
            session.add(lead)
            inserted += 1
    session.commit()
    return inserted


def upsert_company(session: Session, company: Company) -> Company:
    existing = session.scalar(
        select(Company).where(Company.company_slug == company.company_slug)
    )
    if existing is None:
        session.add(company)
        session.commit()
        return company
    for field in (
        "name",
        "domain",
        "email_pattern",
        "email_pattern_conf",
        "is_catch_all",
        "linkedin_url",
        "github_org",
        "headcount_band",
        "enriched_at",
        "status",
        "notes",
    ):
        value = getattr(company, field)
        if value is not None and value != "":
            setattr(existing, field, value)
    session.commit()
    return existing
