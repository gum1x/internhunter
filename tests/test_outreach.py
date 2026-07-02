from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings
from internhunter.core.db import Application, Dossier, Job, get_session, init_db
from internhunter.dossier.pitch import get_pitch, load_pitch
from internhunter.outreach import (
    backfill_pending,
    draft_cold_outreach,
    enrich_application,
    find_dossier,
    format_draft,
)
from internhunter.tracker import track_job

NOW = datetime(2026, 7, 1, tzinfo=UTC)

_CONNECTIONS = """
connections:
  - name: "Pat Prediction"
    relationship: "Polymarket research collaboration"
    firms: [Polymarket]
    domains: [polymarket.com]
"""


def _job(uid: str, company: str, slug: str, domain: str | None = None,
         title: str = "SWE Intern") -> Job:
    now = NOW.replace(tzinfo=None)
    return Job(
        job_uid=uid, ats="greenhouse", board_token=slug,
        canonical_url=f"https://x/{uid}", url_hash=uid, company=company,
        company_slug=slug, company_domain=domain, title=title,
        title_normalized=title.lower(), is_internship=True,
        posted_at=now, first_seen_at=now, last_seen_at=now,
    )


def _dossier(slug: str = "polymarket", name: str = "Polymarket", **overrides: object) -> Dossier:
    values: dict[str, object] = dict(
        company_slug=slug, company_name=name, domain="polymarket.com",
        summary="Runs a prediction market. Users trade event contracts.",
        signal_title="Launched new settlement engine", signal_url="https://polymarket.com/b",
        signal_date="2026-06-15",
        contact_name="Casey Founder", contact_title="Co-founder",
        contact_email="casey@polymarket.com",
        contact_source="https://linkedin.com/in/casey",
        why_fit="I study prediction-market price discovery with CFTC-affiliated faculty",
        confidence="high", built_at=NOW.replace(tzinfo=None),
    )
    values.update(overrides)
    return Dossier(**values)  # type: ignore[arg-type]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    init_db(db_path=tmp_path / "t.db")
    s = get_session()
    yield s
    s.close()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / "connections.yaml").write_text(_CONNECTIONS)
    return Settings(
        db_path=tmp_path / "t.db",
        connections_path=tmp_path / "connections.yaml",
        targets_path=tmp_path / "missing-targets.yaml",
        pitch_path=Path("internhunter/config/pitch.yaml"),
    )


def test_find_dossier_exact_canonical_and_domain(session: Session) -> None:
    session.add(_dossier())
    session.flush()
    assert find_dossier(session, "polymarket", None) is not None
    # canonical name match survives corporate suffixes and different slugs
    assert find_dossier(session, "polymarket-inc", "Polymarket Inc.") is not None
    # domain match catches board-token slugs ("wehrtyou" case)
    assert find_dossier(session, "weird-token", "weird-token", "jobs.polymarket.com") is not None
    assert find_dossier(session, "unrelated", "Unrelated Co", "unrelated.io") is None


def test_find_dossier_resolves_board_token_via_registry(session: Session) -> None:
    from internhunter.core.db import Board

    session.add(_dossier(slug="hudson-river-trading", name="Hudson River Trading",
                         domain="hudsonrivertrading.com"))
    session.add(Board(ats="greenhouse", token="wehrtyou", company="Hudson River Trading"))
    session.flush()
    found = find_dossier(session, "wehrtyou", "wehrtyou", None)
    assert found is not None and found.company_slug == "hudson-river-trading"


def test_draft_cold_outreach_is_specific_and_bounded(session: Session) -> None:
    d = _dossier()
    app = Application(job_uid="j", company="Polymarket", company_slug="polymarket",
                      role="Quant Research Intern")
    pitch = get_pitch("internhunter/config/pitch.yaml")
    draft = draft_cold_outreach(app, d, pitch)
    assert draft is not None
    assert "{{proof_link}}" in draft
    assert "Casey" in draft  # greets the verified contact by first name
    assert "Launched new settlement engine" in draft  # references the real signal
    assert "Quant Research Intern" in draft
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", draft.replace("\n", " ")) if s.strip()]
    assert 3 <= len(sentences) <= 5


def test_draft_cold_outreach_without_contact_greets_team(session: Session) -> None:
    d = _dossier(contact_name=None, contact_email=None, contact_source=None,
                 contact_channel="https://jobs.ashbyhq.com/polymarket")
    app = Application(job_uid="j", company="Polymarket", company_slug="polymarket",
                      role="SWE Intern")
    draft = draft_cold_outreach(app, d, load_pitch("internhunter/config/pitch.yaml"))
    assert draft is not None and "Hi Polymarket team" in draft


def test_draft_requires_dossier() -> None:
    app = Application(job_uid="j", company="X", company_slug="x", role="Intern")
    assert draft_cold_outreach(app, None, load_pitch("nope.yaml")) is None


def test_enrich_attaches_dossier_contact_and_cold_draft(
    session: Session, settings: Settings
) -> None:
    session.add(_dossier(slug="hudson-river-trading", name="Hudson River Trading",
                         domain="hudsonrivertrading.com"))
    job = _job("h1", "wehrtyou", "wehrtyou", "hudsonrivertrading.com",
               title="Quant Intern")
    session.add(job)
    session.flush()
    app = track_job(session, job, settings=settings)
    assert app is not None
    assert app.dossier_slug == "hudson-river-trading"  # matched via domain
    assert app.warm_intro is False
    assert app.contact_name == "Casey Founder"
    assert app.outreach_draft is not None and "{{proof_link}}" in app.outreach_draft
    assert app.intro_draft is None


def test_enrich_warm_path_from_connections(session: Session, settings: Settings) -> None:
    session.add(_dossier())
    job = _job("p1", "Polymarket", "polymarket", "polymarket.com")
    session.add(job)
    session.flush()
    app = track_job(session, job, settings=settings)
    assert app is not None
    assert app.warm_intro is True
    assert app.connection_name == "Pat Prediction"
    assert app.intro_draft is not None  # warm ask generated
    assert app.outreach_draft is None  # cold draft suppressed for warm rows
    assert app.dossier_slug == "polymarket"


def test_enrich_never_overwrites_existing_fields(session: Session, settings: Settings) -> None:
    session.add(_dossier())
    job = _job("p1", "Polymarket", "polymarket")
    session.add(job)
    session.flush()
    app = Application(job_uid="p1", company="Polymarket", company_slug="polymarket",
                      role="Intern", contact_name="My Pick", contact_email="me@pick.com",
                      warm_intro=False, outreach_draft="my hand-written draft")
    session.add(app)
    session.flush()
    enrich_application(session, app, job, settings)
    assert app.contact_name == "My Pick"
    assert app.outreach_draft == "my hand-written draft"


def test_enrich_without_dossier_flags_pending_then_backfills(
    session: Session, settings: Settings
) -> None:
    job = _job("n1", "NewCo", "newco", "newco.io")
    session.add(job)
    session.flush()
    app = track_job(session, job, settings=settings)
    assert app is not None
    assert app.dossier_slug is None  # "no dossier yet"
    assert app.outreach_draft is None

    session.add(_dossier(slug="newco", name="NewCo", domain="newco.io"))
    session.flush()
    assert backfill_pending(session, settings) == 1
    assert app.dossier_slug == "newco"
    assert app.outreach_draft is not None


def test_format_draft_cold_with_dossier(session: Session, settings: Settings) -> None:
    session.add(_dossier())
    job = _job("p1", "Polymarket", "polymarket")
    session.add(job)
    session.flush()
    no_warm = settings.model_copy(update={"connections_path": Path("missing.yaml")})
    app = track_job(session, job, settings=no_warm)
    assert app is not None
    session.flush()
    text = format_draft(session, app)
    assert "❄️ cold outreach" in text
    assert "dossiers/polymarket.md" in text
    assert "Casey Founder" in text
    assert "contact source: https://linkedin.com/in/casey" in text
    assert "{{proof_link}}" in text


def test_format_draft_no_dossier(session: Session, settings: Settings) -> None:
    job = _job("z1", "ZCo", "zco")
    session.add(job)
    session.flush()
    app = track_job(session, job, settings=settings)
    assert app is not None
    text = format_draft(session, app)
    assert "none yet" in text
    assert "no draft yet" in text


def test_format_draft_warm_prints_intro_ask(session: Session, settings: Settings) -> None:
    session.add(_dossier())
    job = _job("p1", "Polymarket", "polymarket", "polymarket.com")
    session.add(job)
    session.flush()
    app = track_job(session, job, settings=settings)
    assert app is not None
    text = format_draft(session, app)
    assert "🤝 warm intro" in text
    assert "Pat Prediction" in text
    assert "would you be open to introducing me" in text
