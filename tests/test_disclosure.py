from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

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
    upsert_disclosure_leads,
)
from internhunter.core.normalize import normalize_company_slug
from internhunter.discovery.disclosure import (
    ingest_oflc,
    lead_from_lca_row,
    leads_from_sbir_award,
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
        "WAGE_RATE_OF_PAY_FROM": "120000",
        "RECEIVED_DATE": "2026-03-01",
    }
    lead = lead_from_lca_row(row, ["15-12"])
    assert lead is not None
    assert lead.email == "dana.lee@acme.com"
    assert lead.company_slug == normalize_company_slug("Acme Robotics Inc")
    assert lead.domain == "acme.com"
    assert lead.role_hint == "hr"
    assert lead.signal["tech"] is True
    assert lead.filed_at is not None


def test_lca_row_skips_non_tech_soc() -> None:
    row = {"EMPLOYER_NAME": "Acme", "SOC_CODE": "29-1141", "EMPLOYER_POC_EMAIL": "x@acme.com"}
    assert lead_from_lca_row(row, ["15-12"]) is None


def test_lca_row_skips_without_any_email() -> None:
    row = {"EMPLOYER_NAME": "Acme", "SOC_CODE": "15-1252"}
    assert lead_from_lca_row(row, ["15-12"]) is None


def test_lca_row_falls_back_to_attorney_email() -> None:
    row = {
        "EMPLOYER_NAME": "Acme",
        "SOC_CODE": "15-1252",
        "AGENT_ATTORNEY_EMAIL_ADDRESS": "Counsel@lawfirm.com",
        "AGENT_ATTORNEY_FIRST_NAME": "Pat",
        "AGENT_ATTORNEY_LAST_NAME": "Roe",
        "LAW_FIRM_NAME_BUSINESS_NAME": "Lawfirm LLP",
    }
    lead = lead_from_lca_row(row, ["15-12"])
    assert lead is not None
    assert lead.email == "counsel@lawfirm.com"
    assert lead.role_hint == "other"
    assert lead.domain is None  # never attribute a law-firm domain to the employer


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
    assert all(lead.source == "sbir" for lead in leads)


def test_disclosure_published_scores_at_least_probable() -> None:
    score, label = score_email(EmailSignals(disclosure_published=True, spf_dmarc=True))
    assert score >= 55.0
    assert label in ("probable", "verified")


def test_find_email_uses_disclosure_provenance() -> None:
    person = DiscoveredPerson(
        full_name="Dana Lee", known_email="dana@acme.com", person_source="oflc_lca"
    )
    result = find_email(person, "acme.com")
    assert result.email == "dana@acme.com"
    assert result.email_status == "disclosure"
    assert result.email_source == "gov:oflc_lca"


def test_gov_disclosure_people_source(tmp_path: Path) -> None:
    init_db(tmp_path / "t.db")
    session = get_session()
    upsert_disclosure_leads(
        session,
        [
            DisclosureLead(
                company_slug="acme",
                company_name="Acme",
                full_name="Dana Lee",
                title="Recruiting Manager",
                email="dana@acme.com",
                role_hint="hr",
                source="oflc_lca",
            )
        ],
    )
    session.close()

    people = discover_people_gov_disclosure("acme")
    assert len(people) == 1
    assert people[0].known_email == "dana@acme.com"
    assert people[0].person_source == "oflc_lca"


def test_ingest_oflc_xlsx_filters_and_signals(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(
        [
            "EMPLOYER_NAME",
            "SOC_CODE",
            "JOB_TITLE",
            "EMPLOYER_POC_FIRST_NAME",
            "EMPLOYER_POC_LAST_NAME",
            "EMPLOYER_POC_EMAIL",
        ]
    )
    sheet.append(["Acme Inc", "15-1252", "SWE", "Dana", "Lee", "dana@acme.com"])
    sheet.append(["Health Co", "29-1141", "Nurse", "Sam", "Roe", "sam@health.com"])
    path = tmp_path / "lca.xlsx"
    workbook.save(path)

    settings = Settings(db_path=tmp_path / "t.db", cache_dir=tmp_path / "cache")
    summary = asyncio.run(ingest_oflc(settings, source=str(path)))

    assert summary.rows == 2
    assert summary.leads == 1  # only the tech (15-12) row becomes a lead
    assert not summary.errors

    session = get_session()
    company = session.scalar(
        select(Company).where(Company.company_slug == normalize_company_slug("Acme Inc"))
    )
    session.close()
    assert company is not None
    assert "disclosure" in (company.notes or {})


def test_ingest_oflc_without_source_reports_error() -> None:
    summary = asyncio.run(ingest_oflc(Settings(oflc_lca_url="")))
    assert summary.errors
    assert summary.leads == 0
