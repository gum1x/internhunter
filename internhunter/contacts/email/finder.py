from __future__ import annotations

from internhunter.contacts.email.harvest import is_role_account
from internhunter.contacts.email.infer import infer_pattern
from internhunter.contacts.email.permute import render_pattern, split_name
from internhunter.contacts.email.priors import default_template, prior_confidence
from internhunter.contacts.score import EmailSignals, score_email
from internhunter.contacts.types import DiscoveredPerson, EmailResult


def _match_scraped(full_name: str, scraped: list[str], domain: str) -> str | None:
    """Return a scraped email whose localpart plausibly matches this person."""
    split = split_name(full_name)
    if split is None:
        return None
    first, last = split
    from internhunter.contacts.email.permute import name_part_variants

    variants = name_part_variants(first, last)
    locals_ = {e.split("@", 1)[0].lower() for e in scraped}
    from internhunter.contacts.email.permute import TEMPLATES

    for template in TEMPLATES:
        for parts in variants:
            rendered = template.format(
                first=parts.first, last=parts.last, f=parts.f, l=parts.l
            )
            if rendered in locals_:
                return f"{rendered}@{domain}"
    return None


def find_email(
    person: DiscoveredPerson,
    domain: str,
    *,
    headcount_band: str | None = None,
    provider: str = "unknown",
    known_pairs: list[tuple[str, str]] | None = None,
    scraped_emails: list[str] | None = None,
    catch_all: bool = False,
    locked_template: str | None = None,
) -> EmailResult:
    """Best email + confidence for a person, using only offline signals.

    Network verification (holehe/SMTP) is layered on afterward by the runner.
    """
    known_pairs = known_pairs or []
    scraped_emails = scraped_emails or []

    # 1. A real, already-known email (GitHub commit, or a government-filing address).
    #    Government-filing addresses are anchored on the email's OWN domain, not the resolved
    #    company domain: a disclosure-only company often has no Job-derived domain, and
    #    resolve_domain would otherwise guess a different one and drop this real address.
    src = person.person_source or ""
    known = (person.known_email or "").lower()
    is_disclosure = src in ("oflc_lca", "oflc_perm", "sbir")
    if known and (is_disclosure or known.endswith("@" + domain.lower())):
        if is_disclosure:
            signals = EmailSignals(disclosure_published=True, catch_all=catch_all)
            status, source_label = "disclosure", f"gov:{src}"
        else:
            signals = EmailSignals(github=True, catch_all=catch_all)
            status, source_label = "github", "github_commit"
        score, label = score_email(signals)
        return EmailResult(
            email=known,
            email_status=status,
            email_source=source_label,
            confidence=score,
            label=label,
            evidence={"source": source_label},
        )

    name = person.full_name or ""

    # 2. Directly scraped/published address matching the person.
    scraped_hit = _match_scraped(name, scraped_emails, domain) if name else None
    if scraped_hit:
        signals = EmailSignals(scraped=True, catch_all=catch_all)
        score, label = score_email(signals)
        return EmailResult(
            email=scraped_hit,
            email_status="scraped",
            email_source="site_scrape",
            confidence=score,
            label=label,
            evidence={"source": "site_scrape"},
        )

    if not name or split_name(name) is None:
        return EmailResult(label="invalid", evidence={"reason": "unsplittable_name"})
    first, last = split_name(name)  # type: ignore[misc]

    # 3. Pattern inference from same-domain corpus.
    template = locked_template
    template_locked = locked_template is not None
    votes = 0
    if template is None:
        inference = infer_pattern(known_pairs, domain)
        template = inference.template
        votes = inference.votes

    if template is not None:
        candidate = render_pattern(template, first, last)
        if candidate:
            email = f"{candidate}@{domain}"
            signals = EmailSignals(
                pattern_votes=votes,
                template_locked=template_locked,  # a real one-email lock confers confidence
                prior_only=False,
                catch_all=catch_all,
                role_account_for_person=is_role_account(email),
            )
            score, label = score_email(signals)
            return EmailResult(
                email=email,
                email_status="guessed",
                email_source=f"pattern:{template}",
                confidence=score,
                label=label,
                evidence={"template": template, "votes": votes, "locked": template_locked},
            )

    # 4. Global provider/size-aware prior (last resort).
    template = default_template(headcount_band, provider)
    candidate = render_pattern(template, first, last)
    if not candidate:
        return EmailResult(label="invalid", evidence={"reason": "no_render"})
    email = f"{candidate}@{domain}"
    signals = EmailSignals(prior_only=True, catch_all=catch_all)
    score, label = score_email(signals)
    score = min(score, prior_confidence(headcount_band) * 100.0)
    label = "probable" if score >= 55 else "guessed"
    return EmailResult(
        email=email,
        email_status="guessed",
        email_source=f"prior:{template}",
        confidence=score,
        label=label,
        evidence={"template": template, "prior": True},
    )
