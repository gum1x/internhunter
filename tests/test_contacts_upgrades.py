from __future__ import annotations

from internhunter.config.settings import Settings
from internhunter.contacts.domain import (
    candidate_domains,
    classify_provider,
    is_company_domain,
    resolve_domain,
)
from internhunter.contacts.score import EmailSignals, score_email
from internhunter.contacts.selfcheck import source_status


# --- domain resolver (C1) ---
def test_is_company_domain_rejects_aggregators() -> None:
    assert is_company_domain("acme.com")
    assert not is_company_domain("boards.greenhouse.io")
    assert not is_company_domain("linkedin.com")
    assert not is_company_domain("www.lever.co")


def test_candidate_domains_from_name_and_slug() -> None:
    cands = candidate_domains("Acme Inc", "acme")
    assert "acme.com" in cands
    assert "acmeinc.com" in cands


def test_resolve_domain_prefers_known() -> None:
    r = resolve_domain("Acme Inc", "acme", known_domain="acme.io", check_mx=False)
    assert r.domain == "acme.io"
    assert r.confidence == 1.0
    assert r.source == "job_metadata"


def test_resolve_domain_rejects_known_aggregator() -> None:
    # a greenhouse host is not the company's email domain -> fall through to a guess
    r = resolve_domain("Acme", "acme", known_domain="boards.greenhouse.io", check_mx=False)
    assert r.domain == "acme.com"
    assert r.confidence < 1.0


def test_provider_from_spf() -> None:
    from internhunter.contacts.domain import provider_from_spf

    assert provider_from_spf("v=spf1 include:spf.protection.outlook.com -all") == "microsoft"
    assert provider_from_spf("v=spf1 include:_spf.google.com ~all") == "google"
    assert provider_from_spf("v=spf1 include:mailgun.org -all") is None
    assert provider_from_spf("not an spf record") is None


def test_name_matches_conservative() -> None:
    from internhunter.contacts.runner import _name_matches

    assert _name_matches("Jane Doe", "Jane Doe") is True
    assert _name_matches("J. Doe", "Jane Doe") is True  # last token + first initial
    assert _name_matches("Mike Doe", "Jane Doe") is False  # different first initial
    assert _name_matches("Jane Smith", "Jane Doe") is False  # different last name
    assert _name_matches("Cher", "Jane Doe") is False  # single token
    assert _name_matches(None, "Jane Doe") is False


def test_classify_provider() -> None:
    assert classify_provider("acme-com.mail.protection.outlook.com") == "microsoft"
    assert classify_provider("aspmx.l.google.com") == "google"
    assert classify_provider("alt1.aspmx.l.google.com") == "google"
    assert classify_provider("mx.zoho.com") == "other"
    assert classify_provider(None) == "unknown"


def test_resolve_domain_fallback_low_confidence() -> None:
    r = resolve_domain("Acme", "acme", known_domain=None, check_mx=False)
    assert r.domain == "acme.com"
    assert r.confidence == 0.3
    assert r.source == "slug_fallback"


# --- new HTTPS verification signals (C3/C4/C8) ---
def test_github_verify_promotes_pattern_guess() -> None:
    base, base_label = score_email(EmailSignals(pattern_votes=2))
    assert base_label == "guessed"  # a bare pattern guess is honestly "guessed"
    promoted, label = score_email(
        EmailSignals(pattern_votes=2, github_account_confirmed=True)
    )
    assert promoted > base
    assert label == "probable"  # a single HTTPS confirmation lifts it to probable


def test_multiple_confirmations_reach_verified() -> None:
    # guessed pattern + 3 independent HTTPS confirmations -> verified (honest ladder)
    s, label = score_email(
        EmailSignals(
            pattern_votes=2,
            github_account_confirmed=True,
            gravatar_confirmed=True,
            holehe_confirmed=True,
        )
    )
    assert label == "verified"


def test_template_locked_reaches_probable() -> None:
    # a real one-email company lock should make teammates' guesses at least "probable"
    score, label = score_email(EmailSignals(template_locked=True, pattern_votes=0))
    assert label == "probable"
    assert score >= 55


def test_find_email_locked_template_is_probable() -> None:
    from internhunter.contacts.email.finder import find_email
    from internhunter.contacts.types import DiscoveredPerson

    person = DiscoveredPerson(full_name="Dana Lin", title="Recruiter")
    r = find_email(person, "acme.com", locked_template="{f}{last}")
    assert r.email == "dlin@acme.com"
    assert r.label == "probable"  # was "guessed" before the votes=0 fix


def test_provider_conditioned_priors() -> None:
    from internhunter.contacts.email.priors import default_template

    assert default_template("tiny", "microsoft") == "{first}.{last}"
    assert default_template("tiny", "google") == "{first}"
    assert default_template("large", "google") == "{first}.{last}"
    assert default_template("tiny", "unknown") == "{first}"  # falls back to size-only


def test_cross_channel_corroboration_boosts_email() -> None:
    base, _ = score_email(EmailSignals(pattern_votes=3))  # 50
    corr, label = score_email(
        EmailSignals(pattern_votes=3, cross_channel_corroborated=True, corroborating_channels=3)
    )
    assert corr == base + 15  # +min(15, 5*3)
    assert label == "probable"  # 65 crosses the 55 threshold
    # the boost is capped at +15 regardless of channel count
    capped, _ = score_email(
        EmailSignals(pattern_votes=3, cross_channel_corroborated=True, corroborating_channels=9)
    )
    assert capped == base + 15


def test_score_channel_rubric() -> None:
    from internhunter.contacts.score import score_channel

    assert score_channel("github", "email_match")[1] == "verified"  # 90
    assert score_channel("x", "gravatar")[1] == "verified"  # 85
    assert score_channel("x", None)[1] == "guessed"  # blind search 50
    # corroboration promotes a blind-search handle
    assert score_channel("x", None, corroborators=2)[0] == 60.0


def test_identity_confirmed_is_definitive() -> None:
    score, label = score_email(
        EmailSignals(mailbox_confirmed=True, pattern_votes=1, identity_confirmed=True)
    )
    assert label == "verified"
    assert score >= 88


def test_locked_pattern_confidence_raised() -> None:
    # a 2-vote locked pattern rose from 30 -> 38, though still "guessed" without verification
    score, label = score_email(EmailSignals(pattern_votes=2))
    assert score == 38
    assert label == "guessed"


# --- self-check (C2) ---
def test_selfcheck_reports_inert_sources() -> None:
    status = source_status(Settings(searxng_url="", contacts_methods="searxng,github"))
    assert status["searxng_dorking"] is False  # no URL -> inert
    assert status["verify_emails"] is True  # on by default now
    status2 = source_status(Settings(searxng_url="http://x:8888", contacts_methods="searxng"))
    assert status2["searxng_dorking"] is True
