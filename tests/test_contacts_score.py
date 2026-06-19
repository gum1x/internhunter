from __future__ import annotations

from internhunter.contacts.score import EmailSignals, score_email


def test_scraped_is_verified() -> None:
    score, label = score_email(EmailSignals(scraped=True))
    assert score == 70
    assert label == "probable"


def test_scraped_plus_holehe_is_verified() -> None:
    score, label = score_email(EmailSignals(scraped=True, holehe_confirmed=True))
    assert score == 88
    assert label == "verified"


def test_smtp_rejected_is_invalid() -> None:
    score, label = score_email(EmailSignals(pattern_votes=3, smtp_rejected=True))
    assert score == 0
    assert label == "invalid"


def test_catch_all_caps_confidence() -> None:
    score, label = score_email(
        EmailSignals(scraped=True, github=True, catch_all=True)
    )
    assert score <= 60
    assert label != "verified"


def test_pattern_votes_scale() -> None:
    assert score_email(EmailSignals(pattern_votes=1))[0] == 15
    assert score_email(EmailSignals(pattern_votes=2))[0] == 38
    assert score_email(EmailSignals(pattern_votes=3))[0] == 50


def test_prior_only_is_guessed() -> None:
    score, label = score_email(EmailSignals(prior_only=True))
    assert score == 10
    assert label == "guessed"


def test_role_account_penalty() -> None:
    base = score_email(EmailSignals(pattern_votes=3))[0]
    penalized = score_email(
        EmailSignals(pattern_votes=3, role_account_for_person=True)
    )[0]
    assert penalized == base - 10


def test_no_mx_is_invalid() -> None:
    score, label = score_email(EmailSignals(scraped=True, mx_present=False))
    assert score == 0
    assert label == "invalid"


def test_spf_dmarc_small_positive() -> None:
    base = score_email(EmailSignals(pattern_votes=1))[0]
    boosted = score_email(EmailSignals(pattern_votes=1, spf_dmarc=True))[0]
    assert boosted == base + 5


def test_pgp_confirmed_single_vote_is_additive_only() -> None:
    # A single pattern vote is too weak to verify on PGP alone: only the +22 bump applies.
    score, label = score_email(EmailSignals(pattern_votes=1, pgp_confirmed=True))
    assert score == 15 + 22
    assert label != "verified"


def test_pgp_confirmed_promotes_with_two_votes() -> None:
    # A 2+ pattern agreement plus an owner-verified key reaches verified.
    score, label = score_email(EmailSignals(pattern_votes=2, pgp_confirmed=True))
    assert score >= 85
    assert label == "verified"


def test_pgp_confirmed_promotes_with_scraped() -> None:
    score, label = score_email(EmailSignals(scraped=True, pgp_confirmed=True))
    assert score >= 85
    assert label == "verified"


def test_smtp_valid_unknown_catch_all_no_bonus() -> None:
    # catch_all unknown (None) must NOT grant the non-catch-all SMTP bonus.
    base = score_email(EmailSignals(pattern_votes=2, smtp_valid=True, catch_all=None))[0]
    known = score_email(EmailSignals(pattern_votes=2, smtp_valid=True, catch_all=False))[0]
    assert known == base + 25


def test_catch_all_none_is_no_penalty() -> None:
    # Unknown catch-all status must not penalize (mirrors the old False behaviour).
    known = score_email(EmailSignals(scraped=True, catch_all=False))[0]
    unknown = score_email(EmailSignals(scraped=True, catch_all=None))[0]
    assert unknown == known


def test_catch_all_true_caps() -> None:
    score, label = score_email(
        EmailSignals(scraped=True, github=True, catch_all=True)
    )
    assert score <= 60
    assert label != "verified"
