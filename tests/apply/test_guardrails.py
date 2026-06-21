from datetime import UTC, datetime, timedelta

from internhunter.apply.applicant import Applicant
from internhunter.apply.guardrails import applications_today, eligible, kill_switch_active, skip_reason
from internhunter.config.settings import Settings
from internhunter.core.db import Application


class _Job:
    def __init__(self, text, job_uid="u1", company_slug="acme"):
        self.description_text = text
        self.title = "SWE Intern"
        self.job_uid = job_uid
        self.company_slug = company_slug


def test_kill_switch_off_by_default():
    assert kill_switch_active(Settings()) is True   # enable_auto_apply defaults False


def test_eligibility_blocks_sponsorship_mismatch():
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="F-1",
                  requires_sponsorship=True, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")
    assert eligible(_Job("We do not provide visa sponsorship for this role."), a) is False
    assert eligible(_Job("Great team, free lunch."), a) is True


def test_applications_today_counts_only_recent_submitted(db_session):
    """Count only submitted applications from the last 24 hours."""
    now = datetime.now(UTC)

    # Recent submitted application (should be counted)
    app1 = Application(job_uid="u1", status="submitted", applied_at=now)
    db_session.add(app1)

    # Old submitted application (should NOT be counted)
    app2 = Application(job_uid="u2", status="submitted", applied_at=now - timedelta(hours=25))
    db_session.add(app2)

    # Recent but not submitted (should NOT be counted)
    app3 = Application(job_uid="u3", status="needs_review", applied_at=now)
    db_session.add(app3)

    db_session.commit()

    assert applications_today(db_session) == 1


def test_skip_reason_blocks_already_applied(db_session):
    """Reject job if already in applications table regardless of status."""
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="US Citizen",
                  requires_sponsorship=False, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")

    # Insert existing application for this job
    existing = Application(job_uid="u1", status="submitted", company_slug="acme")
    db_session.add(existing)
    db_session.commit()

    job = _Job("hi", job_uid="u1", company_slug="acme")
    settings = Settings(enable_auto_apply=True)

    reason = skip_reason(db_session, job, a, settings)
    assert reason is not None
    assert "already" in reason


def test_skip_reason_daily_cap(db_session):
    """Reject if daily cap reached with different company."""
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="US Citizen",
                  requires_sponsorship=False, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")

    now = datetime.now(UTC)

    # Insert one submitted application from a different company
    existing = Application(job_uid="u_other", status="submitted", applied_at=now,
                          company_slug="other-company")
    db_session.add(existing)
    db_session.commit()

    # New job from different company
    job = _Job("hi", job_uid="u_new", company_slug="new-company")
    settings = Settings(enable_auto_apply=True, auto_apply_daily_cap=1)

    reason = skip_reason(db_session, job, a, settings)
    assert reason == "daily cap reached"


def test_skip_reason_per_company_cap(db_session):
    """Reject if per-company cap reached."""
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="US Citizen",
                  requires_sponsorship=False, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")

    # Insert one submitted application for company "acme"
    existing = Application(job_uid="u_existing", status="submitted", company_slug="acme")
    db_session.add(existing)
    db_session.commit()

    # New job for same company
    job = _Job("hi", job_uid="u_new", company_slug="acme")
    settings = Settings(enable_auto_apply=True, auto_apply_daily_cap=99,
                       auto_apply_per_company_cap=1)

    reason = skip_reason(db_session, job, a, settings)
    assert reason is not None
    assert "company" in reason


def test_skip_reason_passes_clean_job(db_session):
    """Return None when job is eligible and all caps are available."""
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="US Citizen",
                  requires_sponsorship=False, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")

    job = _Job("hi", job_uid="u_new", company_slug="new-company")
    settings = Settings(enable_auto_apply=True)

    reason = skip_reason(db_session, job, a, settings)
    assert reason is None
