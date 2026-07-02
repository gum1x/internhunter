"""Dossier builder: one structured, source-backed research file per target firm.

Anti-fabrication design: the LLM (optional) only *summarizes* fetched material and
*selects* a signal from deterministically extracted, dated candidates — it cannot
introduce a URL, person, or number. `validate_synthesis` drops any stage/team_size
value that does not literally appear in the fetched material, and contacts come
exclusively from provenance-carrying tables (contacts / connections) or fall back to
a real careers channel. Confidence is computed by rubric, never self-reported.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import (
    Board,
    Contact,
    DisclosureLead,
    Dossier,
    OfficerLead,
    get_session,
    init_db,
)
from internhunter.core.fetch import build_fetch_context
from internhunter.core.normalize import canonical_company_slug
from internhunter.dossier.pitch import get_pitch
from internhunter.dossier.research import ResearchBundle, SignalCandidate, gather_research
from internhunter.match.targets import TargetFirm, get_targets

_STAGE_RE = re.compile(
    r"\b(pre-?seed|seed(?:\s+round|\s+stage)?|series\s+[a-f]|public(?:ly traded)?|"
    r"bootstrapped|ipo)\b",
    re.IGNORECASE,
)
_TEAM_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})?)\+?\s*(?:people|employees|person team)\b", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class BuildSummary:
    considered: int = 0
    built: int = 0
    skipped_fresh: int = 0
    thin: int = 0
    backfilled: int = 0
    errors: list[str] = field(default_factory=list)


def _two_sentences(text: str) -> str:
    parts = [p.strip() for p in _SENTENCE_RE.split(text.strip()) if p.strip()]
    return " ".join(parts[:2])


def _material_text(bundle: ResearchBundle) -> str:
    chunks = [bundle.description or ""]
    chunks.extend(page.text for page in bundle.pages)
    chunks.extend(f"{k}: {v}" for k, v in bundle.org_facts.items())
    return "\n".join(chunks)


def _stage_from_material(material: str) -> str | None:
    match = _STAGE_RE.search(material)
    return match.group(0).lower().replace("-", " ").strip() if match else None


def _team_from_material(bundle: ResearchBundle, material: str) -> str | None:
    if bundle.org_facts.get("team_size"):
        return bundle.org_facts["team_size"]
    match = _TEAM_RE.search(material)
    return match.group(1) if match else None


def synthesize_heuristic(bundle: ResearchBundle) -> dict[str, Any]:
    """No-LLM synthesis: everything comes straight from deterministic extraction."""
    material = _material_text(bundle)
    summary = _two_sentences(bundle.description or "") or None
    if summary is None and bundle.pages:
        summary = _two_sentences(bundle.pages[0].text) or None
    return {
        "summary": summary,
        "stage": _stage_from_material(material),
        "team_size": _team_from_material(bundle, material),
        "signal": bundle.signals[0] if bundle.signals else None,
        "why_fit": None,  # filled from the pitch angle by the caller
    }


def validate_synthesis(raw: dict[str, Any], bundle: ResearchBundle) -> dict[str, Any]:
    """Clamp LLM output to the fetched material. Anything unverifiable becomes None —
    a blank field beats an invented one."""
    material = _material_text(bundle).lower()
    out: dict[str, Any] = {}

    summary = raw.get("summary")
    out["summary"] = _two_sentences(str(summary)) if isinstance(summary, str) and summary else None

    stage = raw.get("stage")
    if isinstance(stage, str) and stage.strip() and stage.strip().lower() in material:
        out["stage"] = stage.strip().lower()
    else:
        out["stage"] = _stage_from_material(material)

    team = raw.get("team_size")
    if team is not None:
        team = str(team).strip()
    if team and team.lower() in material:
        out["team_size"] = team
    else:
        out["team_size"] = _team_from_material(bundle, material)

    # The LLM selects a signal BY INDEX from our dated candidates; it cannot mint one.
    # An explicit null is respected — "no notable signal" beats presenting a random
    # dated link as news.
    index = raw.get("signal_index")
    signal: SignalCandidate | None = None
    if isinstance(index, int) and 0 <= index < len(bundle.signals):
        signal = bundle.signals[index]
    elif index is None and "signal_index" in raw:
        signal = None  # deliberate "nothing notable" — don't force a random dated link
    elif bundle.signals:
        signal = bundle.signals[0]  # missing/garbled index -> newest candidate
    out["signal"] = signal

    why = raw.get("why_fit")
    out["why_fit"] = str(why).strip() if isinstance(why, str) and why.strip() else None
    return out


_SYNTH_SYSTEM = (
    "You summarize research material about a company for a student's outreach dossier. "
    "Use ONLY the material provided — never outside knowledge, never invented facts. "
    "Respond with a single JSON object: "
    '{"summary": "1-2 plain sentences on what the company actually does, no marketing '
    'language", "stage": "funding stage ONLY if stated in the material else null", '
    '"team_size": "ONLY if stated in the material else null", '
    '"signal_index": <index of the most notable recent-signal candidate, or null>, '
    '"why_fit": "one specific sentence starting with a lowercase letter, combining the '
    "candidate's angle with what the company does; do not add facts about the company "
    'that are not in the material"}'
)


def _synthesize_llm(
    bundle: ResearchBundle, angle: str, settings: Settings
) -> dict[str, Any] | None:
    from internhunter.llm.client import LlmCache, complete, extract_json, get_backend

    pages = "\n\n".join(
        f"[{p.kind}] {p.url}\n{p.text[:1200]}" for p in bundle.pages[:6]
    )
    signals = "\n".join(
        f"{i}: {s.title} ({s.date}) {s.url}" for i, s in enumerate(bundle.signals[:8])
    ) or "(none)"
    facts = json.dumps(bundle.org_facts) if bundle.org_facts else "(none)"
    prompt = (
        f"Company: {bundle.company}\n\nFetched material:\n{pages}\n\n"
        f"Structured facts: {facts}\n\nRecent-signal candidates:\n{signals}\n\n"
        f"Candidate's angle for this company: {angle}\n\nReturn the JSON object."
    )
    try:
        backend = get_backend(settings)
        text = complete(
            prompt,
            backend,
            system=_SYNTH_SYSTEM,
            max_tokens=settings.llm_max_tokens,
            cache=LlmCache(settings.cache_dir),
            model=f"dossier:{settings.llm_model}",
        )
        return validate_synthesis(extract_json(text), bundle)
    except Exception as exc:
        logger.debug("dossier: llm synthesis unavailable for {} ({})", bundle.slug, exc)
        return None


def _db_signals(session: Session, firm_name: str, now: datetime, window_days: int
                ) -> list[SignalCandidate]:
    """Government-verified signals already in the DB: a recent SEC Form D (fundraising)
    or SBIR award beats anything scraped — both carry real filing dates."""
    canonical = canonical_company_slug(firm_name)
    cutoff = now - timedelta(days=window_days)
    signals: list[SignalCandidate] = []
    for lead in session.scalars(select(OfficerLead).where(OfficerLead.company_slug == canonical)):
        if lead.filed_at is not None and lead.filed_at >= cutoff.replace(tzinfo=None):
            signals.append(
                SignalCandidate(
                    title="Filed SEC Form D (new fundraising round)",
                    url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                    f"&company={canonical}",
                    date=lead.filed_at.date().isoformat(),
                    origin="edgar",
                )
            )
            break
    for disclosure in session.scalars(
        select(DisclosureLead).where(DisclosureLead.company_slug == canonical)
    ):
        if disclosure.filed_at is not None and disclosure.filed_at >= cutoff.replace(tzinfo=None):
            signals.append(
                SignalCandidate(
                    title=f"Government filing signal ({disclosure.source})",
                    url="https://www.sbir.gov/awards" if "sbir" in (disclosure.source or "")
                    else "https://www.dol.gov/agencies/eta/foreign-labor/performance",
                    date=disclosure.filed_at.date().isoformat(),
                    origin="disclosure",
                )
            )
            break
    return signals


_CONTACT_ROLE_ORDER = ("founder", "recruiter", "hiring_manager", "eng_manager", "engineer")


def _pick_contact(session: Session, slug: str) -> dict[str, str | None] | None:
    """Best already-discovered person at this firm, with provenance. Never guessed here:
    only rows the contacts pipeline stored with a person_source survive."""
    contacts = list(session.scalars(select(Contact).where(Contact.company_slug == slug)))
    named = [c for c in contacts if c.full_name and c.person_source]
    if not named:
        return None
    rank = {role: i for i, role in enumerate(_CONTACT_ROLE_ORDER)}
    named.sort(
        key=lambda c: (
            rank.get(c.role_category or "", len(rank)),
            -(c.priority or 0.0),
        )
    )
    best = named[0]
    return {
        "name": best.full_name,
        "title": best.title,
        "email": best.email if best.email_status in ("verified", "probable") else None,
        "source": best.linkedin_url or f"contacts:{best.person_source}",
    }


def _fallback_channel(session: Session, slug: str, domain: str | None) -> str | None:
    board = session.scalar(select(Board).where(Board.token == slug))
    board_url = board.board_url if board is not None else None
    if board_url and "api." not in board_url:  # API endpoints aren't a human channel
        return board_url
    if domain:
        return f"https://{domain}/careers"
    return board_url


def compute_confidence(
    summary: str | None,
    signal: SignalCandidate | None,
    contact: dict[str, str | None] | None,
    bundle: ResearchBundle,
) -> str:
    if bundle.thin or not summary:
        return "low"
    if signal is not None and contact is not None:
        return "high"
    return "medium"


def render_markdown(d: Dossier) -> str:
    lines = [
        f"# {d.company_name} — dossier",
        f"_built {d.built_at.date().isoformat()} · confidence: **{d.confidence}**_",
        "",
        "## What they do",
        d.summary or "_Not verified — public pages were unreachable or empty._",
        "",
        "## Stage & size",
        f"- Stage: {d.stage or 'not verified'}",
        f"- Team size: {d.team_size or 'not verified'}",
        "",
        "## Recent signal",
    ]
    if d.signal_title and d.signal_url:
        lines.append(f"- [{d.signal_title}]({d.signal_url}) — {d.signal_date}")
    else:
        lines.append(f"- None found in the last window (checked {d.built_at.date().isoformat()})")
    lines += ["", "## Likely contact"]
    if d.contact_name:
        title = f" — {d.contact_title}" if d.contact_title else ""
        email = f" · {d.contact_email}" if d.contact_email else ""
        lines.append(f"**{d.contact_name}**{title}{email}  ")
        lines.append(f"source: {d.contact_source}")
    else:
        lines.append(
            "No named person verified — do NOT guess one. Best channel: "
            f"{d.contact_channel or 'the posting itself'}"
        )
    lines += ["", "## Why Ryan fits", d.why_fit or "_(no angle configured)_", ""]
    if d.notes:
        lines += ["## Notes", d.notes, ""]
    lines.append("## Sources")
    for source in d.sources or []:
        lines.append(f"- {source.get('url')} ({source.get('kind', 'page')})")
    if not d.sources:
        lines.append("- (none fetched)")
    return "\n".join(lines) + "\n"


def write_files(dossiers: list[Dossier], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {}
    for d in dossiers:
        (directory / f"{d.company_slug}.md").write_text(render_markdown(d), encoding="utf-8")
    for d in dossiers:
        index[d.company_slug] = {
            "company": d.company_name,
            "confidence": d.confidence,
            "built_at": d.built_at.isoformat(),
            "contact": d.contact_name,
            "file": f"{d.company_slug}.md",
        }
    (directory / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True), encoding="utf-8"
    )


def _firm_worklist(session: Session, settings: Settings) -> list[TargetFirm]:
    """targets.yaml firms, plus ad-hoc firms for tracked postings that have no dossier
    yet (a posting whose firm isn't in targets.yaml still deserves research)."""
    from internhunter.core.db import Application, Job

    targets = get_targets(settings.targets_path)
    firms: dict[str, TargetFirm] = {}
    for firm in targets.firms:
        firms.setdefault(firm.slug, firm)
    known = set(firms)
    pending = session.scalars(
        select(Application).where(Application.dossier_slug.is_(None))
    )
    for app in pending:
        slug = app.company_slug or ""
        if not slug or slug in known:
            continue
        job = session.scalar(select(Job).where(Job.job_uid == app.job_uid))
        domain = job.company_domain if job is not None else None
        firms[slug] = TargetFirm(
            name=app.company or slug,
            slug=slug,
            canonical_slug=canonical_company_slug(app.company or slug),
            domains=(domain,) if domain else (),
        )
        known.add(slug)
    return list(firms.values())


async def _build_all(
    settings: Settings,
    only_slug: str | None,
    force: bool,
    limit: int | None,
    now: datetime,
) -> BuildSummary:
    summary = BuildSummary()
    init_db(settings.db_path)
    session = get_session()
    try:
        firms = _firm_worklist(session, settings)
        if only_slug:
            firms = [f for f in firms if f.slug == only_slug]
            if not firms:
                summary.errors.append(f"no firm with slug {only_slug!r} in targets or tracker")
                return summary
        fresh_cutoff = now - timedelta(days=settings.dossier_staleness_days)
        existing = {
            d.company_slug: d for d in session.scalars(select(Dossier))
        }
        worklist: list[TargetFirm] = []
        for firm in firms:
            current = existing.get(firm.slug)
            if (
                not force
                and current is not None
                and current.built_at.replace(tzinfo=UTC) >= fresh_cutoff
            ):
                summary.skipped_fresh += 1
                continue
            worklist.append(firm)
        if limit is not None:
            worklist = worklist[:limit]
        summary.considered = len(worklist) + summary.skipped_fresh

        pitch = get_pitch(settings.pitch_path)
        built: list[Dossier] = []
        async with build_fetch_context(settings) as ctx:
            for firm in worklist:  # sequential on purpose: polite, one firm at a time
                try:
                    dossier = await _build_one(ctx, session, settings, firm, pitch, now)
                except Exception as exc:  # noqa: BLE001 — one firm must not sink the run
                    summary.errors.append(f"{firm.slug}: {exc}")
                    continue
                built.append(dossier)
                summary.built += 1
                if dossier.confidence == "low":
                    summary.thin += 1
        session.commit()
        all_rows = list(session.scalars(select(Dossier)))
        write_files(all_rows, settings.dossier_dir)

        from internhunter.outreach import backfill_pending

        summary.backfilled = backfill_pending(session, settings)
        session.commit()
    finally:
        session.close()
    return summary


async def _build_one(
    ctx: Any,
    session: Session,
    settings: Settings,
    firm: TargetFirm,
    pitch: Any,
    now: datetime,
) -> Dossier:
    domain = firm.domains[0] if firm.domains else None
    bundle = await gather_research(ctx, settings, firm.name, firm.slug, domain, now=now)
    bundle.signals = (
        _db_signals(session, firm.name, now, settings.dossier_signal_days) + bundle.signals
    )

    angle = pitch.angle_for(firm.tags, firm.name)
    synthesis: dict[str, Any] | None = None
    if settings.dossier_use_llm and bundle.pages:
        synthesis = _synthesize_llm(bundle, angle, settings)
    if synthesis is None:
        synthesis = synthesize_heuristic(bundle)
    if not synthesis.get("why_fit"):
        synthesis["why_fit"] = angle or None

    contact = _pick_contact(session, firm.slug)
    signal: SignalCandidate | None = synthesis.get("signal")
    notes: list[str] = list(bundle.errors)
    if contact is None:
        notes.append("no named contact verified; using fallback channel")
    confidence = compute_confidence(synthesis.get("summary"), signal, contact, bundle)

    dossier = session.scalar(select(Dossier).where(Dossier.company_slug == firm.slug))
    if dossier is None:
        dossier = Dossier(company_slug=firm.slug, company_name=firm.name)
        session.add(dossier)
    dossier.company_name = firm.name
    dossier.domain = domain
    dossier.tags = list(firm.tags)
    dossier.summary = synthesis.get("summary")
    dossier.stage = synthesis.get("stage")
    dossier.team_size = synthesis.get("team_size")
    dossier.signal_title = signal.title if signal else None
    dossier.signal_url = signal.url if signal else None
    dossier.signal_date = signal.date if signal else None
    if contact is not None:
        dossier.contact_name = contact["name"]
        dossier.contact_title = contact["title"]
        dossier.contact_email = contact["email"]
        dossier.contact_source = contact["source"]
        dossier.contact_channel = None
    else:
        dossier.contact_name = None
        dossier.contact_title = None
        dossier.contact_email = None
        dossier.contact_source = None
        dossier.contact_channel = _fallback_channel(session, firm.slug, domain)
    dossier.why_fit = synthesis.get("why_fit")
    dossier.confidence = confidence
    dossier.notes = "; ".join(notes) if notes else None
    dossier.sources = [
        {"url": page.url, "kind": page.kind} for page in bundle.pages
    ]
    dossier.built_at = now.replace(tzinfo=None)
    session.flush()
    return dossier


def run_build_dossiers(
    settings: Settings | None = None,
    only_slug: str | None = None,
    force: bool = False,
    limit: int | None = None,
    now: datetime | None = None,
) -> BuildSummary:
    resolved = settings or get_settings()
    moment = now or datetime.now(UTC)
    return asyncio.run(_build_all(resolved, only_slug, force, limit, moment))
