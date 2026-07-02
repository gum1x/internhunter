"""Tracker enrichment: attach the firm's dossier, likely contact, and a
register-correct outreach draft to every tracked posting.

Warm rows (a path exists in connections.yaml) get/keep the intro-request ask; cold
rows get a founder/eng-lead message seeded from the dossier and pitch.yaml, with a
literal ``{{proof_link}}`` placeholder the user fills once. A posting whose firm has
no dossier yet is left flagged (``dossier_slug IS NULL``) and picked up by the next
dossier build's backfill pass — nothing here fabricates a contact or a fact.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Application, Board, Dossier, Job
from internhunter.core.normalize import canonical_company_slug
from internhunter.dossier.pitch import Pitch, get_pitch
from internhunter.referrals import connection_for_job, draft_intro, get_connections

PROOF_PLACEHOLDER = "{{proof_link}}"


def find_dossier(
    session: Session,
    company_slug: str | None,
    company: str | None,
    company_domain: str | None = None,
) -> Dossier | None:
    """Best-effort dossier lookup: exact slug, then canonical company name, then domain.
    (ATS sources sometimes store the board token as the company, so exact slug alone
    would miss e.g. Hudson River Trading behind the 'wehrtyou' greenhouse token.)"""
    if company_slug:
        exact = session.scalar(select(Dossier).where(Dossier.company_slug == company_slug))
        if exact is not None:
            return exact
    dossiers = list(session.scalars(select(Dossier)))
    canonical = canonical_company_slug(company)
    if canonical:
        for d in dossiers:
            if canonical_company_slug(d.company_name) == canonical:
                return d
    domain = (company_domain or "").lower().removeprefix("www.")
    if domain:
        for d in dossiers:
            if d.domain and (domain == d.domain or domain.endswith("." + d.domain)):
                return d
    # Last resort: the slug may be a bare board token (greenhouse 'wehrtyou' = Hudson
    # River Trading); the registry's Board row knows the real company name.
    if company_slug:
        board = session.scalar(select(Board).where(Board.token == company_slug))
        if board is not None and board.company:
            board_canonical = canonical_company_slug(board.company)
            for d in dossiers:
                if canonical_company_slug(d.company_name) == board_canonical:
                    return d
    return None


def _first_name(name: str | None) -> str | None:
    if not name:
        return None
    first = name.split()[0].strip(",")
    return first or None


def draft_cold_outreach(
    app: Application, dossier: Dossier | None, pitch: Pitch
) -> str | None:
    """3-5 specific sentences seeded from verified dossier fields. Returns None when
    there is no dossier — a generic message would waste the outreach edge."""
    if dossier is None:
        return None
    # Prefer the dossier's verified name: ATS snapshots are sometimes a bare board
    # token ("wehrtyou"), and "Hi wehrtyou team" is not a sendable greeting.
    company = dossier.company_name or app.company
    greeting_target = _first_name(dossier.contact_name) or f"{company} team"
    signal_bit = ""
    if dossier.signal_title and dossier.signal_date:
        signal_bit = f" — and saw the {dossier.signal_title} news ({dossier.signal_date})"
    why = (dossier.why_fit or "").strip().rstrip(".")
    proof = pitch.proof_points[0] if pitch.proof_points else "recent shipped work"

    sentences = [
        f"Hi {greeting_target} — I just applied to your {app.role} opening{signal_bit}.",
    ]
    if dossier.summary:
        sentences.append(
            f"I'm reaching out directly because what you're building is squarely my lane: {why}."
            if why
            else "I'm reaching out directly rather than waiting in the applicant pile."
        )
    elif why:
        sentences.append(f"The short version of why I fit: {why}.")
    sentences.append(f"Proof over promises: {PROOF_PLACEHOLDER} ({proof}).")
    sentences.append(
        "If it'd be useful I'd love 15 minutes — or I can send a one-page plan for "
        "what I'd ship in my first month."
    )
    return "\n".join(sentences)


def enrich_application(
    session: Session,
    app: Application,
    job: Job | None,
    settings: Settings | None = None,
) -> Application:
    """Idempotent enrichment of one tracker row: dossier attach, contact fill,
    register-correct draft. Never overwrites user edits or an existing draft."""
    resolved = settings or get_settings()

    # Warm path: if the runner didn't already stamp it, check connections.yaml here so
    # dashboard-tracked postings get the same treatment as alerted ones.
    if not app.warm_intro and job is not None:
        connection = connection_for_job(get_connections(resolved.connections_path), job)
        if connection is not None:
            app.warm_intro = True
            app.connection_name = connection.name
            if app.intro_draft is None:
                app.intro_draft = draft_intro(connection, job)

    dossier = find_dossier(
        session,
        app.company_slug,
        app.company,
        job.company_domain if job is not None else None,
    )
    if dossier is None:
        return app  # dossier_slug stays NULL = "no dossier yet"; backfill will catch it

    app.dossier_slug = dossier.company_slug
    # Upgrade a token-looking snapshot ("wehrtyou") to the verified company name; a
    # name the user typed (different from the raw slug) is never touched.
    if dossier.company_name and (app.company or "") in ("", app.company_slug):
        app.company = dossier.company_name
    if not app.contact_name and dossier.contact_name:
        app.contact_name = dossier.contact_name
        if dossier.contact_email:
            app.contact_email = dossier.contact_email
    if not app.warm_intro and app.outreach_draft is None:
        app.outreach_draft = draft_cold_outreach(app, dossier, get_pitch(resolved.pitch_path))
    return app


def backfill_pending(session: Session, settings: Settings | None = None) -> int:
    """Re-enrich every tracker row still waiting on a dossier (run after each dossier
    build). Returns how many rows got one attached."""
    resolved = settings or get_settings()
    count = 0
    pending = list(session.scalars(select(Application).where(Application.dossier_slug.is_(None))))
    for app in pending:
        job = session.scalar(select(Job).where(Job.job_uid == app.job_uid))
        enrich_application(session, app, job, resolved)
        if app.dossier_slug is not None:
            count += 1
    return count


def format_draft(session: Session, app: Application) -> str:
    """Human-readable enriched view for `internhunter tracker draft <id>`."""
    flag = "🤝 warm intro" if app.warm_intro else "❄️ cold outreach"
    lines = [f"#{app.id} {app.company or app.company_slug} — {app.role} [{flag}]"]
    dossier = (
        session.scalar(select(Dossier).where(Dossier.company_slug == app.dossier_slug))
        if app.dossier_slug
        else None
    )
    if dossier is not None:
        lines.append(
            f"dossier: dossiers/{dossier.company_slug}.md (confidence: {dossier.confidence})"
        )
        if dossier.contact_name:
            title = f" — {dossier.contact_title}" if dossier.contact_title else ""
            email = f" · {dossier.contact_email}" if dossier.contact_email else ""
            lines.append(f"contact: {dossier.contact_name}{title}{email}")
            lines.append(f"contact source: {dossier.contact_source}")
        else:
            lines.append(
                f"contact: no named person verified — channel: {dossier.contact_channel}"
            )
        if dossier.signal_title:
            lines.append(
                f"signal: {dossier.signal_title} ({dossier.signal_date}) {dossier.signal_url}"
            )
    else:
        lines.append("dossier: none yet — run `internhunter dossier build` to research this firm")
    if app.warm_intro and app.connection_name:
        lines.append(f"via: {app.connection_name}")
    draft = app.intro_draft if app.warm_intro else app.outreach_draft
    lines.append("")
    if draft:
        lines.append("--- draft (fill {{proof_link}} before sending) ---")
        lines.append(draft)
    else:
        lines.append("--- no draft yet ---")
        lines.append(
            "a draft appears once this firm has a dossier"
            if not app.warm_intro
            else "warm row without a stored ask — re-run enrichment"
        )
    return "\n".join(lines)
