from __future__ import annotations

from internhunter.contacts.email.infer import lock_from_verified
from internhunter.contacts.score import EmailSignals, score_email
from internhunter.discovery.edgar import _adsh_from_id, parse_form_d


# --- B3 mailbox_confirmed scoring override ---
def test_mailbox_confirmed_with_pattern_is_verified() -> None:
    score, label = score_email(EmailSignals(mailbox_confirmed=True, pattern_votes=1))
    assert label == "verified"
    assert score >= 85


def test_mailbox_confirmed_bypasses_catch_all_cap() -> None:
    # catch-all normally caps at 60; a real mailbox confirmation overrides that
    score, label = score_email(
        EmailSignals(mailbox_confirmed=True, pattern_votes=2, catch_all=True)
    )
    assert label == "verified"
    assert score > 60


def test_mailbox_confirmed_alone_not_auto_verified() -> None:
    # confirmation with no pattern/source signal stays below verified (honest)
    score, label = score_email(EmailSignals(mailbox_confirmed=True))
    assert label != "verified"


# --- B3 verified-sample pattern lock ---
def test_lock_from_one_verified_pair() -> None:
    # a single real (name,email) that maps to exactly one template locks it
    assert lock_from_verified([("John Smith", "jsmith@acme.com")], "acme.com") == "{f}{last}"


def test_lock_skips_ambiguous() -> None:
    # if the localpart matches no template for the name, no lock
    assert lock_from_verified([("John Smith", "xyz@acme.com")], "acme.com") is None


def test_lock_ignores_other_domain() -> None:
    assert lock_from_verified([("John Smith", "jsmith@other.com")], "acme.com") is None


# --- A1 EDGAR Form D parsing ---
_FORM_D = """<?xml version="1.0"?>
<edgarSubmission>
  <primaryIssuer><entityName>Nova AI Software Inc</entityName></primaryIssuer>
  <relatedPersonsList>
    <relatedPersonInfo><relatedPersonName>
      <firstName>Ada</firstName><lastName>Lovelace</lastName>
    </relatedPersonName></relatedPersonInfo>
    <relatedPersonInfo><relatedPersonName>
      <firstName>Alan</firstName><middleName>M</middleName><lastName>Turing</lastName>
    </relatedPersonName></relatedPersonInfo>
  </relatedPersonsList>
  <offeringData><industryGroup>
    <industryGroupType>Other Technology</industryGroupType>
  </industryGroup></offeringData>
</edgarSubmission>"""


def test_parse_form_d() -> None:
    entity, industry, officers = parse_form_d(_FORM_D)
    assert entity == "Nova AI Software Inc"
    assert industry == "Other Technology"
    assert "Ada Lovelace" in officers
    assert "Alan M Turing" in officers


def test_adsh_from_id() -> None:
    assert _adsh_from_id("0001234567-25-000123:primary_doc.xml") == "000123456725000123"
