from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from internhunter.config.settings import Settings, get_settings
from internhunter.contacts.classify import classify_title, role_priority
from internhunter.contacts.email.finder import find_email
from internhunter.contacts.email.harvest import (
    candidate_aliases,
    harvest_github_login_email,
    harvest_security_txt,
    harvest_site_emails,
    harvest_theharvester,
    is_role_account,
)
from internhunter.contacts.email.infer import infer_pattern, lock_from_verified
from internhunter.contacts.people.github_people import discover_people_github
from internhunter.contacts.people.searxng_people import discover_people_searxng
from internhunter.contacts.people.staffspy_people import discover_people_staffspy
from internhunter.contacts.people.team_pages import discover_people_team_pages
from internhunter.contacts.score import EmailSignals, score_email
from internhunter.contacts.select import CompanyTarget, select_companies
from internhunter.contacts.types import DiscoveredPerson, EmailResult
from internhunter.core.db import (
    Company,
    Contact,
    ContactChannel,
    get_session,
    init_db,
    upsert_channels,
    upsert_company,
    upsert_contact,
)
from internhunter.core.fetch import FetchContext, build_fetch_context


@dataclass
class ContactsSummary:
    companies: int = 0
    people_found: int = 0
    emails_found: int = 0
    contacts_inserted: int = 0
    contacts_updated: int = 0
    errors: list[str] = field(default_factory=list)


_STRONG_CHANNEL_SOURCES = {
    "gravatar", "github", "github_social", "github_profile", "email_match", "keybase",
}

# Cap keyless .patch fan-out per company so a company with many GitHub people can't
# trigger an unbounded burst of outbound fetches.
_MAX_PATCH_BACKFILL = 5


def _corroboration_count(person: DiscoveredPerson) -> int:
    """How many identity-linked channels back this person (self-declared/verified)."""
    return sum(
        1 for ch in person.channels
        if ch.get("status") == "verified" or ch.get("source") in _STRONG_CHANNEL_SOURCES
    )


def _identity_confidence(corroboration: int) -> float:
    return {0: 0.0, 1: 40.0, 2: 70.0}.get(corroboration, 90.0)


def _person_channels(
    person: DiscoveredPerson, result: EmailResult | None, domain: str | None
) -> list[dict[str, Any]]:
    """Reach channels for a person, beyond the chosen anchor email on Contact.email:
    their social handles plus any secondary/known email distinct from the anchor."""
    from internhunter.contacts.score import score_channel

    chans: list[dict[str, Any]] = list(person.channels)
    chosen = (result.email if result else None) or ""
    ke = person.known_email
    if ke and ke.lower() != chosen.lower():
        is_work = bool(domain and ke.lower().endswith("@" + domain.lower()))
        chans.append({
            "kind": "work_email" if is_work else "personal_email",
            "value": ke, "source": person.person_source,
            "confidence": None, "status": "guessed",
        })

    corr = _corroboration_count(person)
    for c in chans:
        if c.get("confidence") is not None:
            continue
        if c["kind"] in ("work_email", "personal_email"):
            # a real address (from a commit/registry) -> provenance-based "probable"
            c["confidence"], c["label"], c["status"] = 60.0, "probable", c.get("status", "guessed")
        else:
            c["confidence"], c["label"] = score_channel(
                c["kind"], c.get("source"), max(0, corr - 1)
            )
    return chans


def _dedupe(people: list[DiscoveredPerson]) -> list[DiscoveredPerson]:
    # Cross-source union-find: collapses a person reached via LinkedIn in one source and
    # GitHub in another into a single multi-channel record (with anti-merge conflict guard).
    from internhunter.contacts.dedup import merge_people

    return merge_people(people)


async def _discover_people(
    ctx: FetchContext, settings: Settings, target: CompanyTarget, domain: str | None
) -> list[DiscoveredPerson]:
    methods = {m.strip() for m in settings.contacts_methods.split(",") if m.strip()}
    company_name = target.name or target.company_slug
    people: list[DiscoveredPerson] = []

    if "searxng" in methods and settings.searxng_url:
        try:
            people += await discover_people_searxng(ctx, settings.searxng_url, company_name)
        except Exception as exc:
            ctx.logger.debug("searxng people failed for {}: {}", company_name, exc)
        try:
            from internhunter.contacts.people.searxng_people import discover_social_searxng

            people += await discover_social_searxng(ctx, settings.searxng_url, company_name)
        except Exception as exc:
            ctx.logger.debug("searxng social failed for {}: {}", company_name, exc)

    if "github" in methods:
        org = target.company_slug
        try:
            people += await asyncio.to_thread(
                discover_people_github, org, domain, settings.github_token or None,
                settings.contacts_max_per_company,
            )
        except Exception as exc:
            ctx.logger.debug("github people failed for {}: {}", org, exc)

    if "team" in methods and domain:
        try:
            from internhunter.llm.client import LlmCache, get_backend

            backend = get_backend(settings)
            people += await discover_people_team_pages(
                ctx, domain, backend=backend, cache=LlmCache(settings.cache_dir),
                model=settings.llm_model,
            )
        except Exception as exc:
            ctx.logger.debug("team pages failed for {}: {}", domain, exc)

    if "staffspy" in methods:
        try:
            people += await asyncio.to_thread(
                discover_people_staffspy, company_name, settings.staffspy_session,
                settings.contacts_max_per_company,
            )
        except Exception as exc:
            ctx.logger.debug("staffspy failed for {}: {}", company_name, exc)

    if "git_commits" in methods:
        try:
            from internhunter.contacts.people.git_commits import discover_people_git_commits

            people += await asyncio.to_thread(
                discover_people_git_commits, target.company_slug, domain,
                settings.github_token or None, settings.git_commit_max_repos,
            )
        except Exception as exc:
            ctx.logger.debug("git_commits failed for {}: {}", target.company_slug, exc)

    if "gitlab_commits" in methods:
        try:
            from internhunter.contacts.people.gitlab_commits import (
                discover_people_gitlab_commits,
            )

            people += await asyncio.to_thread(
                discover_people_gitlab_commits, target.company_slug, domain
            )
        except Exception as exc:
            ctx.logger.debug("gitlab_commits failed for {}: {}", target.company_slug, exc)

    if "ats_raw" in methods:
        try:
            from internhunter.contacts.people.ats_raw import discover_people_ats_raw

            people += await asyncio.to_thread(
                discover_people_ats_raw, target.company_slug, domain
            )
        except Exception as exc:
            ctx.logger.debug("ats_raw failed for {}: {}", target.company_slug, exc)

    if "registries" in methods:
        try:
            from internhunter.contacts.email.registries import harvest_registry_people
            from internhunter.core.normalize import normalize_company_slug

            slug = target.company_slug
            candidates = [slug, slug.replace("-", ""), normalize_company_slug(target.name or "")]
            people += await harvest_registry_people(ctx, [c for c in candidates if c])
        except Exception as exc:
            ctx.logger.debug("registries failed for {}: {}", target.company_slug, exc)

    if "gov_disclosure" in methods:
        try:
            from internhunter.contacts.people.gov_disclosure import (
                discover_people_gov_disclosure,
            )

            slugs = [s for s in (target.company_slug, target.name) if s]
            people += await asyncio.to_thread(
                discover_people_gov_disclosure, target.company_slug, slugs
            )
        except Exception as exc:
            ctx.logger.debug("gov_disclosure failed for {}: {}", target.company_slug, exc)

    return _dedupe(people)


def _headcount_band(job_count: int) -> str | None:
    # Crude size proxy from number of open internship reqs. Better than always-None so the
    # provider/size-aware email priors actually fire.
    if job_count <= 0:
        return None
    if job_count < 3:
        return "tiny"
    if job_count < 15:
        return "mid"
    return "large"


def _name_matches(a: str | None, b: str | None) -> bool:
    """Conservative person-name match: same last-name token AND first-initial agreement."""
    if not a or not b:
        return False
    ta = [t for t in re.split(r"[^a-z]+", a.lower()) if t]
    tb = [t for t in re.split(r"[^a-z]+", b.lower()) if t]
    if len(ta) < 2 or len(tb) < 2:
        return False
    return ta[-1] == tb[-1] and ta[0][0] == tb[0][0]


async def _verify_email(
    ctx: FetchContext,
    result: EmailResult,
    settings: Settings,
    provider: str = "unknown",
    person: DiscoveredPerson | None = None,
    domain_trusted: bool = True,
) -> None:
    """Layer HTTPS verification (M365 mailbox check, GitHub, Gravatar, holehe) onto an
    email — including scraped/published addresses (which can now reach 'verified')."""
    if not result.email:
        return
    ev = result.evidence
    signals = EmailSignals(
        scraped=(result.email_status == "scraped"),
        github=(result.email_status == "github"),
        disclosure_published=(result.email_status == "disclosure"),
        pattern_votes=int(ev.get("votes", 0)),
        template_locked=bool(ev.get("locked")),
        prior_only=bool(ev.get("prior")),
        role_account_for_person=is_role_account(result.email),
    )
    changed = False

    # Keyless DNS posture for the email's domain (MX/SPF/DMARC are plain DNS, fast & sync).
    email_domain = result.email.split("@", 1)[1] if "@" in result.email else ""
    if email_domain:
        from internhunter.contacts.email import verify_dns

        try:
            mx = await asyncio.to_thread(verify_dns.mx_hosts, email_domain)
            signals.mx_present = bool(mx)
            if not mx:
                result.email_status = "invalid"
                result.confidence, result.label = 0.0, "invalid"
                ev["mx"] = False
                return
            spf, dmarc = await asyncio.gather(
                asyncio.to_thread(verify_dns.has_spf, email_domain),
                asyncio.to_thread(verify_dns.has_dmarc, email_domain),
            )
            if spf or dmarc:
                signals.spf_dmarc = True
                ev["spf_dmarc"] = True
                changed = True
            if settings.smtp_verify_host:
                ca = await verify_dns.is_catch_all(email_domain, settings.smtp_verify_host)
                signals.catch_all = ca
                if ca is True:
                    ev["catch_all"] = True
                    changed = True
        except Exception:
            pass

    # keys.openpgp.org owner-verified key -> strong proof this exact mailbox is real.
    try:
        from internhunter.contacts.email.openpgp import pgp_email_exists

        if await pgp_email_exists(ctx, result.email):
            signals.pgp_confirmed = True
            ev["pgp"] = True
            changed = True
    except Exception:
        pass

    # Real per-mailbox confirmation for Microsoft 365 domains (the strongest HTTPS signal).
    # Skipped on a slug-guessed domain so a wrong tenant can't be probed by name.
    if provider == "microsoft" and settings.m365_verify and domain_trusted:
        try:
            from internhunter.contacts.email.verify_m365 import m365_confirms

            verdict = await m365_confirms(result.email)
            if verdict is True:
                signals.mailbox_confirmed = True
                ev["m365"] = True
                changed = True
            elif verdict is False:
                result.email_status = "invalid"
                result.confidence, result.label = 0.0, "invalid"
                ev["m365"] = False
                return
        except Exception:
            pass

    if settings.github_token or True:  # commit search works unauthenticated (throttled)
        try:
            from internhunter.contacts.email.verify_github import github_confirms

            ok, login = await github_confirms(result.email, settings.github_token or None)
            if ok:
                signals.github_account_confirmed = True
                ev["github_verified"] = True
                changed = True
                if login and person is not None:  # C3: email->commit->account is near-proof
                    person.github_login = person.github_login or login
                    person.add_channel(
                        "github", f"https://github.com/{login}", "email_match", 90.0, "verified"
                    )
        except Exception:
            pass

    try:
        from internhunter.contacts.channels import classify_url
        from internhunter.contacts.email.verify_gravatar import gravatar_lookup

        grav = await gravatar_lookup(result.email)
        if grav.found:
            signals.gravatar_confirmed = True
            ev["gravatar"] = True
            changed = True
            name = person.full_name if person is not None else None
            if _name_matches(grav.display_name, name):
                signals.identity_confirmed = True
                ev["identity"] = True
            if person is not None:  # C1: persist the verified social handles, not just .found
                for url in grav.social_urls:
                    person.add_channel(classify_url(url), url, "gravatar", 85.0, "verified")
    except Exception:
        pass

    if not changed:  # fall back to holehe only if cheaper signals missed
        try:
            from internhunter.contacts.email.verify_holehe import holehe_confirms

            if await holehe_confirms(result.email):
                signals.holehe_confirmed = True
                ev["holehe"] = True
                changed = True
        except Exception:
            pass

    # Cross-channel corroboration: a person backed by multiple identity-linked channels
    # gets a confidence bump on their (possibly inferred) email.
    if person is not None:
        corr = _corroboration_count(person)
        if corr >= 1:
            signals.cross_channel_corroborated = True
            signals.corroborating_channels = corr
            if corr >= 2:
                signals.identity_confirmed = True
            changed = True

    if changed:
        result.confidence, result.label = score_email(signals)
        result.email_status = "verified" if result.label == "verified" else result.email_status


async def _enrich_company(
    ctx: FetchContext, settings: Settings, target: CompanyTarget
) -> tuple[Company, list[tuple[Contact, list[dict[str, Any]]]], int]:
    from internhunter.contacts.domain import resolve_domain

    resolved_domain = await asyncio.to_thread(
        resolve_domain, target.name, target.company_slug, target.domain
    )
    domain = resolved_domain.domain
    # Only the slug fallback (conf 0.3) is an unverified guess; job_metadata (1.0) and
    # mx_validated (0.7) are backed by real signals. Gate keyless name brute-forcing
    # (M365 mailbox probes) on a real domain so a wrong slug can't spray a stranger's tenant.
    domain_trusted = resolved_domain.confidence >= 0.7
    headcount_band = _headcount_band(target.job_count)

    provider = "unknown"
    if domain:
        from internhunter.contacts.domain import classify_provider_deep

        _d = domain
        provider = await asyncio.to_thread(lambda: classify_provider_deep(_d))
    people = await _discover_people(ctx, settings, target, domain)

    # Build the email corpus: real (name, email) pairs + all known same-domain emails.
    known_pairs: list[tuple[str, str]] = []
    scraped_emails: list[str] = []
    if domain:
        try:
            scraped_emails += await harvest_site_emails(ctx, domain)
        except Exception:
            pass
        try:
            scraped_emails += await harvest_security_txt(ctx, domain)
        except Exception:
            pass
        try:
            from internhunter.contacts.email.rdap import rdap_emails

            scraped_emails += await rdap_emails(ctx, domain, filter_domain=domain)
        except Exception:
            pass
        try:
            scraped_emails += await asyncio.to_thread(harvest_theharvester, domain)
        except Exception:
            pass
        try:
            from internhunter.contacts.people.ats_raw import harvest_ats_emails

            scraped_emails += await asyncio.to_thread(
                harvest_ats_emails, target.company_slug, domain
            )
        except Exception:
            pass
        if settings.searxng_url:
            try:
                from internhunter.contacts.email.harvest import harvest_searxng_emails

                names = [p.full_name for p in people if p.full_name]
                scraped_emails += await harvest_searxng_emails(
                    ctx, settings.searxng_url, domain, names
                )
            except Exception:
                pass
        # Backfill a real email for GitHub-known people via a public commit .patch. Only
        # with a real domain (the domain filters off-domain personal addresses) and bounded
        # so a company with many GitHub people can't trigger unbounded keyless fan-out.
        backfill_attempts = 0
        for person in people:
            if person.known_email or not person.github_login:
                continue
            if backfill_attempts >= _MAX_PATCH_BACKFILL:
                break
            backfill_attempts += 1
            try:
                patch_email = await harvest_github_login_email(
                    ctx, person.github_login, domain
                )
            except Exception:
                patch_email = None
            if patch_email:
                person.known_email = patch_email
    for person in people:
        if not person.known_email:
            continue
        ke = person.known_email.lower()
        scraped_emails.append(ke)
        # Only let a known email teach the company's NAME->email pattern when it is on the
        # company domain AND not a shared/role mailbox — otherwise a disclosure POC on
        # hr@acme.com named "Harold Rosen" would mis-lock the format to {f}{l}.
        on_domain = bool(domain and ke.endswith("@" + domain.lower()))
        if person.full_name and on_domain and not is_role_account(ke):
            known_pairs.append((person.full_name, ke))
    scraped_emails = sorted(set(e.lower() for e in scraped_emails))

    inference = infer_pattern(known_pairs, domain) if domain else None
    # known_pairs are all REAL emails (GitHub commit/profile, ATS, scraped) -> a single one
    # that maps to exactly one template locks the company format; else fall back to votes>=2.
    locked_template: str | None = None
    if domain:
        locked_template = lock_from_verified(known_pairs, domain)
        if locked_template is None and inference and inference.votes >= 2:
            locked_template = inference.template

    # Classify + rank, keep the top N per company.
    from internhunter.llm.client import LlmCache, get_backend

    backend = None
    cache = None
    if settings.llm_base_url or settings.llm_backend in ("local", "api", "cli"):
        try:
            backend = get_backend(settings)
            cache = LlmCache(settings.cache_dir)
        except Exception:
            backend = None
    for person in people:
        # Preserve a curated role_category from a structured source (disclosure POC->hr,
        # SBIR PI->hiring_manager, ATS creator->recruiter); only classify free-text titles.
        if person.role_category in (None, "other"):
            person.role_category = classify_title(
                person.title, backend, cache, settings.llm_model
            )
    # Find emails for a generous candidate set (role-priority first), then re-rank by
    # contactability and truncate AFTER — so a reachable recruiter beats an unreachable VP.
    people.sort(key=lambda p: role_priority(p.role_category), reverse=True)
    candidates = people[: settings.contacts_max_per_company * 2]

    scored: list[tuple[float, DiscoveredPerson, EmailResult | None]] = []
    emails_found = 0
    for person in candidates:
        result: EmailResult | None = None
        if domain:
            # On Microsoft 365 domains, brute-force the person's name formats against the
            # keyless mailbox check first — a confirmed hit is a *verified* address, no
            # corpus needed. Falls back to corpus/pattern inference otherwise.
            m365_email: str | None = None
            if (
                provider == "microsoft"
                and settings.m365_verify
                and person.full_name
                and domain_trusted
            ):
                try:
                    from internhunter.contacts.email.verify_m365 import m365_resolve

                    m365_email = await m365_resolve(person.full_name, domain)
                except Exception:
                    m365_email = None
            if m365_email:
                # The confirmed mailbox matches this person's name format — a pattern
                # observation of 1 — so it clears the team's mailbox+source verified bar.
                confidence, label = score_email(
                    EmailSignals(mailbox_confirmed=True, pattern_votes=1)
                )
                result = EmailResult(
                    email=m365_email,
                    email_status="verified",
                    email_source="m365_resolve",
                    confidence=confidence,
                    label=label,
                    evidence={"m365": True},
                )
            else:
                result = find_email(
                    person, domain,
                    headcount_band=headcount_band,
                    provider=provider,
                    known_pairs=known_pairs,
                    scraped_emails=scraped_emails,
                    catch_all=False,
                    locked_template=locked_template,
                )
                if result.email and settings.verify_emails:
                    await _verify_email(
                        ctx, result, settings, provider, person, domain_trusted
                    )
        contactability = (result.confidence / 100.0) if (result and result.email) else 0.1
        rank = role_priority(person.role_category) * (0.4 + 0.6 * contactability)
        scored.append((rank, person, result))

    scored.sort(key=lambda t: t[0], reverse=True)
    scored = scored[: settings.contacts_max_per_company]

    records: list[tuple[Contact, list[dict[str, Any]]]] = []
    for _rank, person, result in scored:
        if result and result.email:
            emails_found += 1
        contact = Contact(
            company_slug=target.company_slug,
            company_domain=domain,
            full_name=person.full_name,
            title=person.title,
            role_category=person.role_category,
            priority=role_priority(person.role_category),
            linkedin_url=person.linkedin_url,
            github_login=person.github_login,
            email=result.email if result else None,
            email_status=result.email_status if result else "guessed",
            email_source=result.email_source if result else None,
            confidence=result.confidence if result else None,
            label=result.label if result else None,
            person_source=person.person_source,
            evidence=result.evidence if result else {},
        )
        person_channels = _person_channels(person, result, domain)
        contact.evidence = {
            **(contact.evidence or {}),
            "identity_confidence": _identity_confidence(_corroboration_count(person)),
            "channel_count": len(person_channels),
        }
        records.append((contact, person_channels))

    # Recruiting aliases (careers@/jobs@/...) as standalone high-value contacts.
    if domain:
        alias_hits = [a for a in candidate_aliases(domain) if a in scraped_emails]
        for alias in alias_hits:
            records.append((
                Contact(
                    company_slug=target.company_slug,
                    company_domain=domain,
                    full_name=None,
                    title="Recruiting inbox",
                    role_category="recruiter",
                    priority=0.7,
                    email=alias,
                    email_status="scraped",
                    email_source="recruiting_alias",
                    confidence=80.0,
                    label="verified",
                    person_source="alias",
                    evidence={"alias": True},
                ),
                [],
            ))
            emails_found += 1

    company = Company(
        company_slug=target.company_slug,
        name=target.name,
        domain=domain,
        domain_confidence=resolved_domain.confidence,
        email_pattern=locked_template or (inference.template if inference else None),
        email_pattern_conf=(1.0 if locked_template else None),
        headcount_band=headcount_band,
        enriched_at=datetime.now(UTC),
        status="done",
        notes={
            "people": len(people),
            "corpus": len(known_pairs),
            "domain_source": resolved_domain.source,
        },
    )
    return company, records, emails_found


def _persist_company(
    company: Company, records: list[tuple[Contact, list[dict[str, Any]]]]
) -> tuple[int, int, int]:
    """Upsert one company's contacts + channels in its own session and commit. Sync
    (called via asyncio.to_thread) so per-company results land as soon as they're found."""
    session = get_session()
    inserted = updated = 0
    try:
        upsert_company(session, company)
        for contact, chan_dicts in records:
            row, was_inserted = upsert_contact(session, contact)
            inserted += int(was_inserted)
            updated += int(not was_inserted)
            objs = [
                ContactChannel(
                    kind=c["kind"], value=c["value"], source=c.get("source"),
                    confidence=c.get("confidence"), status=c.get("status", "guessed"),
                    label=c.get("label"), verified=bool(c.get("verified")),
                )
                for c in chan_dicts if c.get("value")
            ]
            if objs:
                upsert_channels(session, row.id, objs)
        session.commit()
    finally:
        session.close()
    return inserted, updated, len(records)


async def find_contacts(
    limit: int | None = 50,
    only_slug: str | None = None,
    settings: Settings | None = None,
) -> ContactsSummary:
    resolved = settings or get_settings()
    methods = {m.strip() for m in resolved.contacts_methods.split(",") if m.strip()}
    if (("team" in methods) or ("staffspy" in methods)) and not resolved.enable_browser:
        resolved = resolved.model_copy(update={"enable_browser": resolved.enrich_use_browser})
    init_db(resolved.db_path)

    session = get_session()
    try:
        targets = select_companies(
            session, limit=limit, min_score=resolved.contacts_min_fit, only_slug=only_slug
        )
    finally:
        session.close()

    summary = ContactsSummary()
    if not targets:
        return summary

    sem = asyncio.Semaphore(max(1, resolved.http_concurrency // 4))

    async with build_fetch_context(resolved) as ctx:
        async def work(target: CompanyTarget) -> None:
            async with sem:
                try:
                    company, records, emails_found = await _enrich_company(
                        ctx, resolved, target
                    )
                except Exception as exc:
                    summary.errors.append(f"{target.company_slug}: {exc}")
                    return
                # Persist THIS company immediately (off-thread) so the dashboard climbs
                # live instead of waiting for the whole batch to finish.
                ins, upd, people = await asyncio.to_thread(
                    _persist_company, company, records
                )
                summary.companies += 1
                summary.people_found += people
                summary.emails_found += emails_found
                summary.contacts_inserted += ins
                summary.contacts_updated += upd

        await asyncio.gather(*(work(t) for t in targets))
    return summary


def run_find_contacts(
    limit: int | None = 50,
    only_slug: str | None = None,
    settings: Settings | None = None,
) -> ContactsSummary:
    """Sync wrapper for the CLI and APScheduler."""
    return asyncio.run(find_contacts(limit=limit, only_slug=only_slug, settings=settings))
