from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from internhunter.config.settings import Settings
from internhunter.contacts.email.finder import find_email
from internhunter.contacts.people.gov_disclosure import discover_people_gov_disclosure
from internhunter.contacts.score import EmailSignals, score_email
from internhunter.contacts.types import DiscoveredPerson
from internhunter.core.db import (
    Company,
    DisclosureLead,
    get_session,
    init_db,
    upsert_company,
    upsert_disclosure_leads,
)
from internhunter.core.normalize import canonical_company_slug
from internhunter.discovery import disclosure as disc
from internhunter.discovery.disclosure import (
    _pick,
    ingest_oflc,
    ingest_sbir,
    lead_from_lca_row,
    leads_from_sbir_award,
    tech_company_of,
)


def test_lca_row_tech_with_poc_email() -> None:
    row = {
        "EMPLOYER_NAME": "Acme Robotics Inc",
        "SOC_CODE": "15-1252",
        "SOC_TITLE": "Software Developers",
        "JOB_TITLE": "Software Engineer",
        "EMPLOYER_POC_FIRST_NAME": "Dana",
        "EMPLOYER_POC_LAST_NAME": "Lee",
        "EMPLOYER_POC_JOB_TITLE": "Recruiting Manager",
        "EMPLOYER_POC_EMAIL": "Dana.Lee@acme.com",
        "WAGE_RATE_OF_PAY_FROM_1": "120000",
        "RECEIVED_DATE": "2026-03-01",
    }
    lead = lead_from_lca_row(row, ["15-11", "15-12"])
    assert lead is not None
    assert lead.email == "dana.lee@acme.com"
    assert lead.company_slug == canonical_company_slug("Acme Robotics Inc")  # suffix-stripped
    assert lead.domain == "acme.com"
    assert lead.role_hint == "hr"
    assert lead.signal["tech"] is True
    assert lead.filed_at is not None


def test_lca_row_covers_2010_soc_codes() -> None:
    row = {"EMPLOYER_NAME": "Acme", "SOC_CODE": "15-1132", "EMPLOYER_POC_EMAIL": "x@acme.com"}
    assert lead_from_lca_row(row, ["15-11", "15-12"]) is not None


def test_lca_row_skips_non_tech_soc() -> None:
    row = {"EMPLOYER_NAME": "Acme", "SOC_CODE": "29-1141", "EMPLOYER_POC_EMAIL": "x@acme.com"}
    assert lead_from_lca_row(row, ["15-11", "15-12"]) is None


def test_lca_row_skips_without_poc_email() -> None:
    row = {"EMPLOYER_NAME": "Acme", "SOC_CODE": "15-1252"}
    assert lead_from_lca_row(row, ["15-12"]) is None


def test_attorney_only_row_yields_no_contact_but_still_a_signal() -> None:
    # The employer POC email is absent; only the immigration attorney's email is present.
    # We must NOT harvest the attorney as a contact, but the tech filing still counts.
    row = {
        "EMPLOYER_NAME": "Acme",
        "SOC_CODE": "15-1252",
        "AGENT_ATTORNEY_EMAIL_ADDRESS": "counsel@lawfirm.com",
        "AGENT_ATTORNEY_FIRST_NAME": "Pat",
        "AGENT_ATTORNEY_LAST_NAME": "Roe",
    }
    assert lead_from_lca_row(row, ["15-12"]) is None
    assert tech_company_of(row, ["15-12"]) == ("Acme", "15-1252")


def test_pick_skips_nan_and_error_cells() -> None:
    assert _pick({"a": float("nan")}, "a") is None
    assert _pick({"a": "#N/A"}, "a") is None
    assert _pick({"a": "  "}, "a") is None
    assert _pick({"a": "real"}, "a") == "real"


def test_lca_row_rejects_nan_email() -> None:
    row = {"EMPLOYER_NAME": "Acme", "SOC_CODE": "15-1252", "EMPLOYER_POC_EMAIL": float("nan")}
    assert lead_from_lca_row(row, ["15-12"]) is None


def test_sbir_award_yields_poc_and_pi() -> None:
    award = {
        "firm": "Beta Labs",
        "company_url": "https://www.betalabs.io",
        "poc_name": "Sam Poc",
        "poc_email": "sam@betalabs.io",
        "pi_name": "Pat PI",
        "pi_email": "pat@betalabs.io",
        "award_amount": "250000",
    }
    leads = leads_from_sbir_award(award)
    assert len(leads) == 2
    assert {lead.email for lead in leads} == {"sam@betalabs.io", "pat@betalabs.io"}
    assert all(lead.domain == "betalabs.io" for lead in leads)
    by_role = {lead.role_hint: lead for lead in leads}
    assert by_role["hiring_manager"].full_name == "Pat PI"  # PI -> hiring_manager
    assert by_role["hr"].full_name == "Sam Poc"


def test_disclosure_published_scores_at_least_probable() -> None:
    score, label = score_email(EmailSignals(disclosure_published=True, spf_dmarc=True))
    assert score >= 55.0
    assert label in ("probable", "verified")


def test_find_email_anchors_disclosure_on_email_domain_not_resolved_domain() -> None:
    # resolve_domain guessed a different domain than the real one in the filing; the verified
    # address must still surface (anchored on its own domain), not get replaced by a guess.
    person = DiscoveredPerson(
        full_name="Dana Lee", known_email="dana@acme.com", person_source="oflc_lca"
    )
    result = find_email(person, "acme-robotics-guess.com")
    assert result.email == "dana@acme.com"
    assert result.email_status == "disclosure"
    assert result.email_source == "gov:oflc_lca"


def test_gov_disclosure_people_join_is_canonical(tmp_path: Path) -> None:
    init_db(tmp_path / "t.db")
    session = get_session()
    upsert_disclosure_leads(
        session,
        [
            DisclosureLead(
                company_slug=canonical_company_slug("Google LLC"),  # stored canonical
                company_name="Google LLC",
                full_name="Dana Lee",
                title="Recruiting Manager",
                email="dana@google.com",
                role_hint="hr",
                source="oflc_lca",
            )
        ],
    )
    session.close()

    # The job board slugs this company plainly as "google" — the canonical join must bridge it.
    people = discover_people_gov_disclosure("google")
    assert len(people) == 1
    assert people[0].known_email == "dana@google.com"
    assert people[0].role_category == "hr"


def test_upsert_disclosure_leads_idempotent_on_null_email(tmp_path: Path) -> None:
    init_db(tmp_path / "t.db")
    session = get_session()
    lead = lambda: DisclosureLead(  # noqa: E731
        company_slug="beta", company_name="Beta", full_name="Pat PI", email=None,
        role_hint="hiring_manager", source="sbir",
    )
    assert upsert_disclosure_leads(session, [lead()]) == 1
    assert upsert_disclosure_leads(session, [lead()]) == 0  # no duplicate growth
    rows = list(session.scalars(select(DisclosureLead)))
    session.close()
    assert len(rows) == 1


def test_ingest_oflc_enriches_existing_company(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["EMPLOYER_NAME", "SOC_CODE", "EMPLOYER_POC_EMAIL", "", ""])  # blank dup headers
    sheet.append(["Acme Inc", "15-1252", "dana@acme.com"])  # ragged: trailing cols missing
    sheet.append(["Health Co", "29-1141", "sam@health.com"])
    path = tmp_path / "lca.xlsx"
    workbook.save(path)

    settings = Settings(db_path=tmp_path / "t.db", cache_dir=tmp_path / "cache")
    init_db(settings.db_path)
    session = get_session()
    upsert_company(session, Company(company_slug="acme", name="Acme Inc", status="pending"))
    session.close()

    summary = asyncio.run(ingest_oflc(settings, source=str(path)))
    assert summary.rows == 2
    assert summary.leads == 1  # only the tech row, and it has a POC email
    assert summary.companies == 1  # the pre-existing Acme company got the signal
    assert not summary.errors

    session = get_session()
    company = session.scalar(select(Company).where(Company.company_slug == "acme"))
    lead = session.scalar(select(DisclosureLead))
    boosted = list(
        session.scalars(
            select(Company.company_slug).where(
                func.json_extract(Company.notes, "$.disclosure").isnot(None)
            )
        )
    )
    session.close()
    assert company is not None and "disclosure" in (company.notes or {})
    assert lead is not None and lead.email == "dana@acme.com"
    assert "acme" in boosted  # the match/score boost query finds it


def test_ingest_sbir_mocked(tmp_path: Path, monkeypatch: Any) -> None:
    awards = [
        {"firm": "Beta Labs", "company_url": "betalabs.io",
         "pi_name": "Pat PI", "pi_email": "pat@betalabs.io"}
    ]

    class _Ctx:
        async def get_json(self, *_a: Any, **_k: Any) -> Any:
            return awards

    @contextlib.asynccontextmanager
    async def _fake_build(_settings: Any):  # type: ignore[no-untyped-def]
        yield _Ctx()

    monkeypatch.setattr(disc, "build_fetch_context", _fake_build)
    settings = Settings(db_path=tmp_path / "t.db", cache_dir=tmp_path / "cache")
    summary = asyncio.run(ingest_sbir(settings))
    assert summary.rows == 1
    assert summary.leads == 1
    session = get_session()
    lead = session.scalar(select(DisclosureLead))
    session.close()
    assert lead is not None
    assert lead.email == "pat@betalabs.io"
    assert lead.role_hint == "hiring_manager"


def test_ingest_oflc_without_source_reports_error() -> None:
    summary = asyncio.run(ingest_oflc(Settings(oflc_lca_url="")))
    assert summary.errors
    assert summary.leads == 0
