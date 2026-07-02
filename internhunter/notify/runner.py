"""Push-alert runner: detect newly discovered postings that match the target/keyword
filter layer, push them (Telegram first-class), mark them notified, and record each in
the pipeline tracker with the warm-intro flag + draft from the referral engine.

Runs on the scheduler every ``notify_interval_min`` and from ``internhunter notify``.
Delivery is at-least-once per channel but exactly-once per job overall: a job's
``notified_at`` is stamped only after some channel actually accepted it, so transient
API failures retry on the next run instead of dropping the alert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Job, get_session, init_db
from internhunter.match.targets import TargetMatch, evaluate_job, get_targets
from internhunter.notify.select import _is_clear_slop
from internhunter.referrals import Connection, connection_for_job, draft_intro, get_connections
from internhunter.tracker import track_job

_CHANNELS = ("telegram", "discord", "ntfy", "feed")


@dataclass
class Alert:
    job: Job
    match: TargetMatch
    connection: Connection | None


@dataclass
class NotifySummary:
    candidates: int = 0
    selected: int = 0
    over_cap: int = 0
    sent: dict[str, int] = field(default_factory=dict)
    marked: int = 0
    tracked: int = 0
    warm: int = 0
    errors: list[str] = field(default_factory=list)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _sort_key(alert: Alert) -> tuple[int, float]:
    firm = alert.match.firm
    bucket = 2
    if firm is not None:
        bucket = 0 if firm.priority == "high" else 1
    return (bucket, -(alert.job.discovery_score or 0.0))


def select_alerts(
    jobs: list[Job],
    settings: Settings,
    now: datetime | None = None,
) -> list[Alert]:
    """Filter candidate jobs down to alerts: target/keyword match (or score bar), slop
    suppressed, deduped by job_uid, best-first."""
    moment = now or datetime.now(UTC)
    targets = get_targets(settings.targets_path)
    connections = get_connections(settings.connections_path)
    cutoff = moment - timedelta(hours=settings.notify_lookback_hours)

    alerts: list[Alert] = []
    seen: set[str] = set()
    for job in jobs:
        if job.job_uid in seen:
            continue
        seen.add(job.job_uid)
        first_seen = _aware(job.first_seen_at)
        if first_seen is not None and first_seen < cutoff:
            continue
        if _is_clear_slop(job):
            continue
        match = evaluate_job(job, targets)
        if not match.matched and match.reasons:
            continue  # hard veto (exclude keyword / location) also blocks score alerts
        score_ok = (
            not settings.notify_require_target_match
            and job.discovery_score is not None
            and job.discovery_score >= settings.notify_min_fit
            and bool(job.is_internship)
        )
        if not (match.matched or score_ok):
            continue
        alerts.append(Alert(job=job, match=match, connection=connection_for_job(connections, job)))
    alerts.sort(key=_sort_key)
    return alerts


def _deliver(
    alerts: list[Alert],
    channels: set[str],
    settings: Settings,
    summary: NotifySummary,
    now: datetime,
) -> set[str]:
    """Fan out to every configured channel; returns job_uids accepted by at least one.
    Telegram sends per job (each failure isolated); the others are batch."""
    delivered: set[str] = set()

    if "telegram" in channels and settings.telegram_bot_token and settings.telegram_chat_id:
        from internhunter.notify.telegram import build_telegram_message, send_telegram

        ok = 0
        for alert in alerts:
            text = build_telegram_message(
                alert.job, alert.connection, now=now, reasons=alert.match.reasons
            )
            try:
                status = send_telegram(
                    text, settings.telegram_bot_token, settings.telegram_chat_id
                )
            except Exception as exc:  # noqa: BLE001 — one bad send must not kill the run
                summary.errors.append(f"telegram {alert.job.job_uid}: {exc}")
                continue
            if 200 <= status < 300:
                ok += 1
                delivered.add(alert.job.job_uid)
            else:
                summary.errors.append(f"telegram {alert.job.job_uid}: HTTP {status}")
        summary.sent["telegram"] = ok

    jobs = [a.job for a in alerts]
    if "discord" in channels and settings.discord_webhook_url:
        from internhunter.notify.discord import build_discord_payload, send_discord

        try:
            status = send_discord(build_discord_payload(jobs), settings.discord_webhook_url)
            if 200 <= status < 300:
                summary.sent["discord"] = len(jobs)
                delivered.update(j.job_uid for j in jobs)
            else:
                summary.errors.append(f"discord: HTTP {status}")
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"discord: {exc}")

    if "ntfy" in channels and settings.ntfy_topic_url:
        from internhunter.notify.ntfy import build_ntfy_message, send_ntfy

        try:
            status = send_ntfy(build_ntfy_message(jobs), settings.ntfy_topic_url)
            if 200 <= status < 300:
                summary.sent["ntfy"] = len(jobs)
                delivered.update(j.job_uid for j in jobs)
            else:
                summary.errors.append(f"ntfy: HTTP {status}")
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"ntfy: {exc}")

    if "feed" in channels:
        from internhunter.notify.feed import write_feed

        try:
            write_feed(jobs, settings.feed_path)
            summary.sent["feed"] = len(jobs)
            delivered.update(j.job_uid for j in jobs)
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"feed: {exc}")

    return delivered


def run_notify(
    settings: Settings | None = None,
    channel: str = "all",
    now: datetime | None = None,
    dry_run: bool = False,
) -> NotifySummary:
    resolved = settings or get_settings()
    moment = now or datetime.now(UTC)
    channels = set(_CHANNELS) if channel == "all" else {channel}
    summary = NotifySummary()

    init_db(resolved.db_path)
    session = get_session()
    try:
        cutoff = moment - timedelta(hours=resolved.notify_lookback_hours)
        candidates = list(
            session.scalars(
                select(Job).where(Job.notified_at.is_(None), Job.first_seen_at >= cutoff)
            )
        )
        summary.candidates = len(candidates)
        alerts = select_alerts(candidates, resolved, now=moment)
        if len(alerts) > resolved.notify_max_per_run:
            summary.over_cap = len(alerts) - resolved.notify_max_per_run
            alerts = alerts[: resolved.notify_max_per_run]
        summary.selected = len(alerts)
        summary.warm = sum(1 for a in alerts if a.connection is not None)
        if not alerts or dry_run:
            return summary

        delivered = _deliver(alerts, channels, resolved, summary, moment)
        if not delivered:
            if not summary.errors:
                summary.errors.append(
                    "no delivery channel configured — set INTERNHUNTER_TELEGRAM_BOT_TOKEN "
                    "+ INTERNHUNTER_TELEGRAM_CHAT_ID (or discord/ntfy), or use --channel feed"
                )
            return summary

        for alert in alerts:
            if alert.job.job_uid not in delivered:
                continue
            alert.job.notified_at = moment.replace(tzinfo=None)
            summary.marked += 1
            if resolved.notify_track_alerts:
                intro = (
                    draft_intro(alert.connection, alert.job)
                    if alert.connection is not None
                    else None
                )
                tracked = track_job(
                    session,
                    alert.job,
                    stage="found",
                    warm_intro=alert.connection is not None,
                    connection_name=alert.connection.name if alert.connection else None,
                    intro_draft=intro,
                )
                if tracked is not None:
                    summary.tracked += 1
        session.commit()
    finally:
        session.close()
    if summary.errors:
        for error in summary.errors[:5]:
            logger.warning("notify: {}", error)
    return summary
