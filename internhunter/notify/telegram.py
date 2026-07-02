"""Telegram push channel (Bot API sendMessage).

One message per job so each alert stands alone on the phone: company, role, direct
apply link, posting age, and the warm-intro / cold-apply flag from the referral engine.
Token/chat id come from env (INTERNHUNTER_TELEGRAM_BOT_TOKEN / _TELEGRAM_CHAT_ID).
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

import httpx

from internhunter.core.db import Job
from internhunter.referrals import Connection

_API_BASE = "https://api.telegram.org"


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=False)


def _age(job: Job, now: datetime) -> str:
    stamp = job.posted_at or job.first_seen_at
    if stamp is None:
        return "age unknown"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    delta = now - stamp
    minutes = int(delta.total_seconds() // 60)
    if minutes < 0:
        return "just posted"
    if minutes < 60:
        return f"posted {minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"posted {hours}h ago"
    return f"posted {hours // 24}d ago"


def build_telegram_message(
    job: Job,
    connection: Connection | None = None,
    now: datetime | None = None,
    reasons: tuple[str, ...] = (),
) -> str:
    moment = now or datetime.now(UTC)
    company = _esc(job.company or job.company_slug)
    lines = [
        f"<b>{_esc(job.title)}</b> @ {company}",
        f"{_esc(job.location_normalized or job.location_raw or 'location n/a')}"
        + (" · remote-ok" if job.is_remote else ""),
        f"{_age(job, moment)}",
        f'<a href="{html.escape(job.canonical_url, quote=True)}">Apply directly</a>',
    ]
    if job.discovery_score is not None:
        lines.append(f"score {job.discovery_score:.2f}")
    if reasons:
        lines.append(_esc(" · ".join(reasons)))
    if connection is not None:
        via = connection.relationship or "your network"
        lines.append(f"🤝 <b>Warm intro:</b> {_esc(connection.name)} — {_esc(via)}")
        if connection.contact:
            lines.append(f"reach: {_esc(connection.contact)}")
    else:
        lines.append("❄️ Cold apply")
    return "\n".join(lines)


def send_telegram(
    text: str,
    bot_token: str,
    chat_id: str,
    timeout: float = 15.0,
) -> int:
    """POST one message; returns the HTTP status (200 = delivered). Network errors
    propagate to the caller, which leaves the job un-marked so it retries next run."""
    response = httpx.post(
        f"{_API_BASE}/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=timeout,
    )
    return response.status_code
