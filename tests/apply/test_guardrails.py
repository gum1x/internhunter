from internhunter.apply.applicant import Applicant
from internhunter.apply.guardrails import eligible, kill_switch_active
from internhunter.config.settings import Settings


class _Job:
    def __init__(self, text):
        self.description_text = text
        self.title = "SWE Intern"


def test_kill_switch_off_by_default():
    assert kill_switch_active(Settings()) is True   # enable_auto_apply defaults False


def test_eligibility_blocks_sponsorship_mismatch():
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="F-1",
                  requires_sponsorship=True, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")
    assert eligible(_Job("We do not provide visa sponsorship for this role."), a) is False
    assert eligible(_Job("Great team, free lunch."), a) is True
