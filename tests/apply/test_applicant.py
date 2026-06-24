from internhunter.apply.applicant import Applicant, load_applicant, validate_applicant


def test_validate_reports_missing_required_fields():
    a = Applicant(full_name="", email="a@b.com", phone="", work_authorization="US Citizen",
                  requires_sponsorship=False, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")
    missing = validate_applicant(a)
    assert "full_name" in missing and "phone" in missing
    assert "email" not in missing


def test_load_applicant_from_yaml(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "applicant:\n  full_name: Jane Doe\n  email: jane@x.com\n  phone: '555'\n"
        "  work_authorization: US Citizen\n  requires_sponsorship: true\n",
        encoding="utf-8",
    )
    from internhunter.config.settings import Settings
    a = load_applicant(Settings(profile_path=p))
    assert a.full_name == "Jane Doe"
    assert a.requires_sponsorship is True
    assert validate_applicant(a) == []


def test_validate_treats_none_as_missing(tmp_path):
    """None values from YAML blanks (e.g. 'phone:') should be reported as missing."""
    p = tmp_path / "profile.yaml"
    p.write_text(
        "applicant:\n  full_name: Jane Doe\n  email: jane@x.com\n  phone:\n"
        "  work_authorization: US Citizen\n",
        encoding="utf-8",
    )
    from internhunter.config.settings import Settings
    a = load_applicant(Settings(profile_path=p))
    # YAML 'phone:' with no value parses to None; validate should report it as missing
    missing = validate_applicant(a)
    assert "phone" in missing
