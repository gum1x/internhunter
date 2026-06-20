from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmailSignals:
    scraped: bool = False  # email published on the company site / matches a known address
    github: bool = False  # email came from a GitHub commit (real, self-reported)
    disclosure_published: bool = False  # real email from a public gov filing (OFLC/SBIR)
    pattern_votes: int = 0  # K known same-domain emails agreeing on the pattern
    prior_only: bool = False  # used only the size-aware global prior
    holehe_confirmed: bool = False  # registered on real sites (HTTPS verification)
    github_account_confirmed: bool = False  # email authored GitHub commits (HTTPS verify)
    gravatar_confirmed: bool = False  # email has a Gravatar profile (HTTPS verify)
    mailbox_confirmed: bool = False  # this exact mailbox exists (M365 GetCredentialType, HTTPS)
    identity_confirmed: bool = False  # a verifier's profile name matched THIS person
    template_locked: bool = False  # company format locked from a real on-domain email
    cross_channel_corroborated: bool = False  # person confirmed on multiple platforms
    corroborating_channels: int = 0  # how many independent agreeing channels
    smtp_valid: bool = False  # SMTP RCPT accepted on a non-catch-all domain
    smtp_rejected: bool = False  # SMTP RCPT 550 -> mailbox does not exist
    catch_all: bool | None = False  # True=accepts everything (SMTP no signal); None=unknown
    role_account_for_person: bool = False  # role inbox where a person was expected
    mx_present: bool = True  # domain publishes MX records (DNS); only the runner sets False
    #   from a real DNS lookup. Defaults True so non-DNS callers stay unaffected.
    spf_dmarc: bool = False  # domain publishes SPF and/or DMARC -> well-managed mail
    pgp_confirmed: bool = False  # owner-verified key on keys.openpgp.org (HTTPS proof)


# Base confidence for a NON-email channel by how it was sourced.
_CHANNEL_SOURCE_BASE: dict[str, float] = {
    "email_match": 90.0,      # email -> commit -> github account (near-proof)
    "github": 90.0,           # canonical github identity
    "keybase": 90.0,          # cryptographic proof
    "gravatar": 85.0,         # verified_accounts attached to a confirmed mailbox
    "github_social": 85.0,    # self-declared on the person's github
    "github_profile": 80.0,   # twitter_username / blog on github profile
    "bluesky_domain": 95.0,   # custom-domain handle == self-proving company affiliation
    "site_relme": 80.0,       # bidirectional rel=me
}


def _label_for(score: float) -> str:
    if score >= 85.0:
        return "verified"
    if score >= 55.0:
        return "probable"
    return "guessed"


def score_channel(kind: str, source: str | None, corroborators: int = 0) -> tuple[float, str]:
    """Confidence for a non-email reach channel (social handle / site)."""
    base = _CHANNEL_SOURCE_BASE.get(source or "", 50.0)  # blind name-search default
    base += min(15.0, 5.0 * corroborators)
    base = max(0.0, min(100.0, base))
    return base, _label_for(base)


def score_email(signals: EmailSignals) -> tuple[float, str]:
    """Combine signals into a 0–100 confidence and a label.

    Labels: verified >=85 · probable 55–84 · guessed <55 · invalid 0.
    """
    if signals.smtp_rejected:
        return 0.0, "invalid"

    # No MX (set False only by the runner's real DNS lookup) -> the domain can't receive
    # mail at all, so any address on it is invalid.
    if not signals.mx_present:
        return 0.0, "invalid"

    score = 0.0
    if signals.scraped:
        score += 70.0
    if signals.github:
        score += 65.0
    if signals.disclosure_published:
        score += 65.0  # a real, government-published address (employer POC / SBIR PI)

    if signals.pattern_votes >= 3:
        score += 50.0
    elif signals.pattern_votes == 2:
        score += 38.0  # a 2+ same-domain pattern is highly reliable
    elif signals.pattern_votes == 1:
        score += 15.0
    elif signals.prior_only:
        score += 10.0

    # HTTPS-based verification signals (work despite the blocked port 25). A single
    # strong confirmation is enough to promote a pattern guess toward "verified".
    if signals.github_account_confirmed:
        score += 22.0
    if signals.gravatar_confirmed:
        score += 20.0
    if signals.holehe_confirmed:
        score += 18.0
    if signals.smtp_valid and not signals.catch_all:
        score += 25.0

    # A verified key on keys.openpgp.org proves the mailbox is real and owner-controlled
    # (the owner confirmed it by email) — a strong HTTPS signal, like a Gravatar hit.
    if signals.pgp_confirmed:
        score += 22.0
    # SPF/DMARC don't validate a mailbox, but a well-managed mail domain makes a
    # pattern-inferred address marginally more credible (modest, prior-sized).
    if signals.spf_dmarc:
        score += 5.0

    # A confirmed mailbox (M365 GetCredentialType) queries identity, not SMTP — so it
    # holds even on a catch-all domain and, with any real source, means "verified".
    if signals.mailbox_confirmed:
        score += 45.0
        if (
            signals.pattern_votes >= 1
            or signals.scraped
            or signals.github
            or signals.disclosure_published
        ):
            score = max(score, 85.0)
        # the verifier confirmed THIS person's name -> definitively verified
        if signals.identity_confirmed:
            score = max(score, 88.0)

    # An owner-verified PGP key is near-proof the address is real -> promote to "verified"
    # whenever any corpus/source signal already backs the local-part.
    if signals.pgp_confirmed and (
        signals.pattern_votes >= 1
        or signals.scraped
        or signals.github
        or signals.disclosure_published
    ):
        score = max(score, 85.0)

    # Company format locked from a REAL on-domain email -> teammates' guesses are at least
    # "probable" (you'd actually send to them); a verifier can still push to "verified".
    if signals.template_locked:
        score = max(score, 55.0)

    # A person confirmed on multiple platforms (GitHub + site + Gravatar...) with a matching
    # name is more certainly real -> their inferred email is more trustworthy.
    if signals.cross_channel_corroborated:
        score += min(15.0, 5.0 * signals.corroborating_channels)

    if signals.role_account_for_person:
        score -= 10.0

    cap = 100.0
    if signals.catch_all and not signals.mailbox_confirmed:
        score -= 15.0
        cap = 60.0  # can never confirm a mailbox on a catch-all domain via SMTP

    score = max(0.0, min(cap, score))

    if score >= 85.0:
        label = "verified"
    elif score >= 55.0:
        label = "probable"
    else:
        label = "guessed"
    return score, label
