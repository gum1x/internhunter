from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

import internhunter.dossier.build as build_mod
from internhunter.config.settings import Settings
from internhunter.core.db import (
    Application,
    Board,
    Contact,
    Dossier,
    Job,
    OfficerLead,
    get_session,
    init_db,
)
from internhunter.dossier.build import (
    compute_confidence,
    render_markdown,
    run_build_dossiers,
    synthesize_heuristic,
    validate_synthesis,
)
from internhunter.dossier.research import PageSnapshot, ResearchBundle, SignalCandidate

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

_TARGETS = """
firms:
  - name: Polymarket
    domains: [polymarket.com]
    tags: [prediction-markets]
    priority: high
  - name: Ghost Co
    tags: [ai]
"""


def _bundle(
    signals: list[SignalCandidate] | None = None,
    description: str | None = "TinyCo builds prediction market infra. It settles event contracts.",
    pages: bool = True,
) -> ResearchBundle:
    bundle = ResearchBundle(company="TinyCo", slug="tinyco", domain="tinyco.com")
    if pages:
        bundle.pages = [
            PageSnapshot(
                url="https://tinyco.com",
                kind="homepage",
                text="TinyCo builds prediction market infra. We are a seed stage team of "
                "12 people building settlement.",
            )
        ]
        bundle.fetched_urls = {"https://tinyco.com"}
    bundle.description = description
    bundle.signals = signals or []
    return bundle


def test_synthesize_heuristic_extracts_from_material() -> None:
    out = synthesize_heuristic(_bundle())
    assert out["summary"] == (
        "TinyCo builds prediction market infra. It settles event contracts."
    )
    assert out["stage"] == "seed stage"
    assert out["team_size"] == "12"


def test_validate_synthesis_drops_unsupported_values() -> None:
    bundle = _bundle(
        signals=[SignalCandidate("Launch", "https://tinyco.com/l", "2026-06-01", "blog")]
    )
    raw = {
        "summary": "One. Two. Three sentences should be clipped.",
        "stage": "series c",  # NOT in material -> replaced by material scan (seed stage)
        "team_size": "500",  # NOT in material -> replaced by material scan (12)
        "signal_index": 99,  # out of range -> first candidate
        "why_fit": "because reasons",
    }
    out = validate_synthesis(raw, bundle)
    assert out["summary"] == "One. Two."
    assert out["stage"] == "seed stage"
    assert out["team_size"] == "12"
    assert out["signal"] is not None and out["signal"].url == "https://tinyco.com/l"
    assert out["why_fit"] == "because reasons"


def test_validate_synthesis_respects_explicit_null_signal() -> None:
    bundle = _bundle(
        signals=[SignalCandidate("Some dated link", "https://tinyco.com/l", "2026-06-01", "blog")]
    )
    out = validate_synthesis({"summary": "S.", "signal_index": None}, bundle)
    assert out["signal"] is None  # LLM judged no candidate notable — don't force one
    # ...but a response that never mentions signals falls back to the newest candidate
    out = validate_synthesis({"summary": "S."}, bundle)
    assert out["signal"] is not None


def test_validate_synthesis_keeps_supported_values() -> None:
    bundle = _bundle()
    out = validate_synthesis({"summary": "S.", "stage": "seed stage", "team_size": "12"}, bundle)
    assert out["stage"] == "seed stage"
    assert out["team_size"] == "12"
    assert out["signal"] is None


def test_confidence_rubric() -> None:
    signal = SignalCandidate("t", "https://x", "2026-06-01", "blog")
    contact = {"name": "A", "title": None, "email": None, "source": "contacts:github"}
    ok = _bundle()
    assert compute_confidence(None, signal, contact, ok) == "low"
    assert compute_confidence("s", None, contact, ok) == "medium"
    assert compute_confidence("s", signal, None, ok) == "medium"
    assert compute_confidence("s", signal, contact, ok) == "high"
    thin = _bundle(pages=False)
    thin.pages = []
    assert compute_confidence("s", signal, contact, thin) == "low"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    (tmp_path / "targets.yaml").write_text(_TARGETS)
    settings = Settings(
        db_path=tmp_path / "t.db",
        targets_path=tmp_path / "targets.yaml",
        connections_path=tmp_path / "none.yaml",
        pitch_path=Path("internhunter/config/pitch.yaml"),
        dossier_dir=tmp_path / "dossiers",
        dossier_use_llm=False,
    )
    init_db(settings.db_path)

    async def fake_gather(
        ctx: object, s: Settings, company: str, slug: str, domain: str | None, now=None
    ) -> ResearchBundle:
        if domain is None:
            bundle = ResearchBundle(company=company, slug=slug, domain=None)
            bundle.errors = ["no domain configured in targets.yaml"]
            return bundle
        bundle = _bundle(
            signals=[SignalCandidate(
                "Launched clearinghouse product", f"https://{domain}/blog/x", "2026-06-20", "blog"
            )]
        )
        bundle.company, bundle.slug, bundle.domain = company, slug, domain
        return bundle

    monkeypatch.setattr(build_mod, "gather_research", fake_gather)
    yield settings


def test_build_creates_dossiers_files_and_index(env: Settings) -> None:
    summary = run_build_dossiers(settings=env, now=NOW)
    assert summary.built == 2
    assert summary.errors == []

    session = get_session()
    rows = {d.company_slug: d for d in session.scalars(select(Dossier))}
    session.close()
    assert set(rows) == {"polymarket", "ghost-co"}
    pm = rows["polymarket"]
    assert pm.summary is not None and "prediction market" in pm.summary
    assert pm.signal_url == "https://polymarket.com/blog/x"
    assert pm.why_fit is not None and "Polymarket" in pm.why_fit
    assert pm.confidence == "medium"  # signal but no named contact
    ghost = rows["ghost-co"]
    assert ghost.confidence == "low"
    assert ghost.summary is None

    assert (env.dossier_dir / "polymarket.md").exists()
    assert (env.dossier_dir / "index.json").exists()
    md = (env.dossier_dir / "polymarket.md").read_text()
    assert "confidence: **medium**" in md
    assert "do NOT guess" in md  # no fabricated contact


def test_build_is_incremental_and_force_rebuilds(env: Settings) -> None:
    first = run_build_dossiers(settings=env, now=NOW)
    assert first.built == 2
    second = run_build_dossiers(settings=env, now=NOW)
    assert second.built == 0
    assert second.skipped_fresh == 2
    forced = run_build_dossiers(settings=env, now=NOW, force=True)
    assert forced.built == 2


def test_build_only_unknown_slug_errors(env: Settings) -> None:
    summary = run_build_dossiers(settings=env, only_slug="nope", now=NOW)
    assert summary.built == 0
    assert summary.errors and "nope" in summary.errors[0]


def test_build_uses_verified_contact_with_provenance(env: Settings) -> None:
    session = get_session()
    session.add(Contact(company_slug="polymarket", full_name="Casey Founder",
                        title="Co-founder", role_category="founder", priority=1.0,
                        email="casey@polymarket.com", email_status="verified",
                        person_source="team_pages",
                        linkedin_url="https://linkedin.com/in/casey"))
    session.add(Contact(company_slug="polymarket", full_name="No Provenance",
                        role_category="recruiter", priority=9.0, person_source=None))
    session.commit()
    session.close()

    run_build_dossiers(settings=env, now=NOW)
    session = get_session()
    d = session.scalar(select(Dossier).where(Dossier.company_slug == "polymarket"))
    session.close()
    assert d is not None
    assert d.contact_name == "Casey Founder"
    assert d.contact_source == "https://linkedin.com/in/casey"
    assert d.contact_email == "casey@polymarket.com"
    assert d.confidence == "high"


def test_build_fallback_channel_from_board(env: Settings) -> None:
    session = get_session()
    session.add(Board(ats="ashby", token="polymarket", company="Polymarket",
                      board_url="https://jobs.ashbyhq.com/polymarket"))
    session.commit()
    session.close()
    run_build_dossiers(settings=env, now=NOW)
    session = get_session()
    d = session.scalar(select(Dossier).where(Dossier.company_slug == "polymarket"))
    session.close()
    assert d is not None
    assert d.contact_name is None
    assert d.contact_channel == "https://jobs.ashbyhq.com/polymarket"


def test_build_includes_edgar_db_signal(env: Settings) -> None:
    session = get_session()
    session.add(OfficerLead(company_slug="polymarket", company_name="Polymarket",
                            full_name="Officer", source="edgar",
                            filed_at=datetime(2026, 6, 25)))
    session.commit()
    session.close()
    run_build_dossiers(settings=env, now=NOW)
    session = get_session()
    d = session.scalar(select(Dossier).where(Dossier.company_slug == "polymarket"))
    session.close()
    assert d is not None
    assert d.signal_title == "Filed SEC Form D (new fundraising round)"
    assert d.signal_date == "2026-06-25"


def test_build_picks_up_pending_tracker_firm_not_in_targets(env: Settings) -> None:
    session = get_session()
    job = Job(job_uid="x1", ats="greenhouse", board_token="mysteryco",
              canonical_url="https://x/1", url_hash="x1", company="Mystery Co",
              company_slug="mysteryco", company_domain="mysteryco.io",
              title="SWE Intern", title_normalized="swe intern", is_internship=True)
    session.add(job)
    session.flush()
    session.add(Application(job_uid="x1", status="To Apply", company="Mystery Co",
                            company_slug="mysteryco"))
    session.commit()
    session.close()

    summary = run_build_dossiers(settings=env, now=NOW)
    assert summary.built == 3  # 2 targets + the ad-hoc tracked firm
    assert summary.backfilled == 1

    session = get_session()
    d = session.scalar(select(Dossier).where(Dossier.company_slug == "mysteryco"))
    app = session.scalar(select(Application).where(Application.job_uid == "x1"))
    session.close()
    assert d is not None and d.domain == "mysteryco.io"
    assert app is not None and app.dossier_slug == "mysteryco"
    assert app.outreach_draft is not None and "{{proof_link}}" in app.outreach_draft


def test_render_markdown_sections() -> None:
    d = Dossier(
        company_slug="tinyco", company_name="TinyCo", summary="Does X. Sells Y.",
        stage="seed", team_size="12", signal_title="Launch", signal_url="https://t/x",
        signal_date="2026-06-01", contact_name="Casey Founder", contact_title="CEO",
        contact_source="https://linkedin.com/in/casey", why_fit="fits because Z",
        confidence="high", sources=[{"url": "https://tinyco.com", "kind": "homepage"}],
        built_at=NOW.replace(tzinfo=None),
    )
    md = render_markdown(d)
    for fragment in ("# TinyCo — dossier", "Does X. Sells Y.", "seed", "12",
                     "[Launch](https://t/x) — 2026-06-01", "Casey Founder", "CEO",
                     "fits because Z", "https://tinyco.com"):
        assert fragment in md
