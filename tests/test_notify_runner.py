from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from internhunter.config.settings import Settings
from internhunter.core.db import Application, Job, get_session, init_db
from internhunter.notify.runner import run_notify, select_alerts

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

_TARGETS = """
firms:
  - name: Polymarket
    domains: [polymarket.com]
    priority: high
keywords:
  include: [intern, "founding engineer"]
  exclude: [senior]
"""

_CONNECTIONS = """
connections:
  - name: "Pat Prediction"
    relationship: "Polymarket research collaboration"
    firms: [Polymarket]
    domains: [polymarket.com]
"""


def _job(
    uid: str,
    title: str,
    company: str = "Acme",
    slug: str = "acme",
    domain: str | None = None,
    score: float | None = None,
    first_seen: datetime | None = None,
    is_internship: bool = True,
    notified_at: datetime | None = None,
    quality_verdict: str | None = None,
    quality_confidence: float | None = None,
) -> Job:
    seen = (first_seen or NOW - timedelta(hours=1)).replace(tzinfo=None)
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token=slug,
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company=company,
        company_slug=slug,
        company_domain=domain,
        title=title,
        title_normalized=title.lower(),
        is_internship=is_internship,
        location_normalized="Remote",
        is_remote=True,
        posted_at=seen,
        first_seen_at=seen,
        last_seen_at=seen,
        discovery_score=score,
        notified_at=notified_at,
        quality_verdict=quality_verdict,
        quality_confidence=quality_confidence,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / "targets.yaml").write_text(_TARGETS)
    (tmp_path / "connections.yaml").write_text(_CONNECTIONS)
    return Settings(
        db_path=tmp_path / "t.db",
        targets_path=tmp_path / "targets.yaml",
        connections_path=tmp_path / "connections.yaml",
        telegram_bot_token="TOKEN",
        telegram_chat_id="42",
        notify_min_fit=0.6,
        notify_lookback_hours=48,
        notify_max_per_run=20,
        feed_path=tmp_path / "feed.xml",
    )


@pytest.fixture
def db(settings: Settings) -> Iterator[Settings]:
    init_db(settings.db_path)
    yield settings


def _seed(*jobs: Job) -> None:
    session = get_session()
    session.add_all(jobs)
    session.commit()
    session.close()


def _telegram_route(status: int = 200) -> respx.Route:
    return respx.post("https://api.telegram.org/botTOKEN/sendMessage").mock(
        return_value=httpx.Response(status, json={"ok": status == 200})
    )


def test_select_alerts_target_firm_and_keyword(db: Settings) -> None:
    jobs = [
        _job("pm", "Quant Intern", company="Polymarket", slug="polymarket",
             domain="polymarket.com"),
        _job("kw", "Founding Engineer", company="Tiny", slug="tiny",
             is_internship=False),
        _job("nomatch", "Accountant", is_internship=False),
    ]
    alerts = select_alerts(jobs, db, now=NOW)
    uids = [a.job.job_uid for a in alerts]
    assert uids == ["pm", "kw"]  # high-priority target firm sorts first
    assert alerts[0].connection is not None
    assert alerts[0].connection.name == "Pat Prediction"
    assert alerts[1].connection is None


def test_select_alerts_score_path_requires_internship(db: Settings) -> None:
    jobs = [
        _job("hi", "Data Wrangler Intern", score=0.9),
        _job("lo", "Data Wrangler Intern", score=0.2, first_seen=NOW - timedelta(hours=2)),
    ]
    # retitle so the include keyword doesn't match; only the score path applies
    for j in jobs:
        j.title = "Data Wrangler"
        j.title_normalized = "data wrangler"
    alerts = select_alerts(jobs, db, now=NOW)
    assert [a.job.job_uid for a in alerts] == ["hi"]


def test_select_alerts_lookback_excludes_old_jobs(db: Settings) -> None:
    old = _job("old", "Quant Intern", company="Polymarket", slug="polymarket",
               first_seen=NOW - timedelta(days=30))
    alerts = select_alerts([old], db, now=NOW)
    assert alerts == []


def test_select_alerts_suppresses_slop(db: Settings) -> None:
    slop = _job("slop", "Software Intern", company="Polymarket", slug="polymarket",
                quality_verdict="ghost", quality_confidence=95.0)
    assert select_alerts([slop], db, now=NOW) == []


def test_select_alerts_exclude_veto_beats_score(db: Settings) -> None:
    job = _job("sr", "Senior Intern Coordinator", score=0.95)
    assert select_alerts([job], db, now=NOW) == []


@respx.mock
def test_run_notify_end_to_end_marks_and_tracks(db: Settings) -> None:
    route = _telegram_route()
    _seed(
        _job("pm", "Quant Intern", company="Polymarket", slug="polymarket",
             domain="polymarket.com"),
        _job("cold", "Founding Engineer", company="Tiny", slug="tiny",
             is_internship=False),
    )
    summary = run_notify(settings=db, channel="telegram", now=NOW)
    assert summary.candidates == 2
    assert summary.selected == 2
    assert summary.sent["telegram"] == 2
    assert summary.marked == 2
    assert summary.tracked == 2
    assert summary.warm == 1
    assert route.call_count == 2

    session = get_session()
    jobs = {j.job_uid: j for j in session.scalars(select(Job))}
    assert jobs["pm"].notified_at is not None
    assert jobs["cold"].notified_at is not None
    apps = {a.job_uid: a for a in session.scalars(select(Application))}
    assert apps["pm"].status == "To Apply"
    assert apps["pm"].warm_intro is True
    assert apps["pm"].connection_name == "Pat Prediction"
    assert apps["pm"].intro_draft is not None
    assert "Polymarket" in apps["pm"].intro_draft
    assert apps["cold"].warm_intro is False
    assert apps["cold"].intro_draft is None
    session.close()


@respx.mock
def test_run_notify_is_idempotent(db: Settings) -> None:
    route = _telegram_route()
    _seed(_job("pm", "Quant Intern", company="Polymarket", slug="polymarket"))
    first = run_notify(settings=db, channel="telegram", now=NOW)
    second = run_notify(settings=db, channel="telegram", now=NOW)
    assert first.marked == 1
    assert second.selected == 0
    assert route.call_count == 1


@respx.mock
def test_run_notify_failure_leaves_job_unmarked_for_retry(db: Settings) -> None:
    _telegram_route(status=500)
    _seed(_job("pm", "Quant Intern", company="Polymarket", slug="polymarket"))
    summary = run_notify(settings=db, channel="telegram", now=NOW)
    assert summary.sent["telegram"] == 0
    assert summary.marked == 0
    assert summary.errors

    session = get_session()
    job = session.scalar(select(Job).where(Job.job_uid == "pm"))
    assert job is not None and job.notified_at is None
    assert session.scalar(select(Application)) is None
    session.close()


@respx.mock
def test_run_notify_network_error_is_survived(db: Settings) -> None:
    respx.post("https://api.telegram.org/botTOKEN/sendMessage").mock(
        side_effect=httpx.ConnectError("boom")
    )
    _seed(_job("pm", "Quant Intern", company="Polymarket", slug="polymarket"))
    summary = run_notify(settings=db, channel="telegram", now=NOW)
    assert summary.marked == 0
    assert any("boom" in e for e in summary.errors)


def test_run_notify_dry_run_sends_and_marks_nothing(db: Settings) -> None:
    _seed(_job("pm", "Quant Intern", company="Polymarket", slug="polymarket"))
    summary = run_notify(settings=db, channel="telegram", now=NOW, dry_run=True)
    assert summary.selected == 1
    assert summary.sent == {}
    session = get_session()
    job = session.scalar(select(Job).where(Job.job_uid == "pm"))
    assert job is not None and job.notified_at is None
    session.close()


def test_run_notify_empty_db(db: Settings) -> None:
    summary = run_notify(settings=db, channel="telegram", now=NOW)
    assert summary.candidates == 0
    assert summary.selected == 0
    assert summary.errors == []


@respx.mock
def test_run_notify_caps_per_run_and_holds_rest(db: Settings) -> None:
    capped = db.model_copy(update={"notify_max_per_run": 2})
    route = _telegram_route()
    _seed(*[
        _job(f"j{i}", "Quant Intern", company="Polymarket", slug="polymarket",
             score=0.5 + i / 100)
        for i in range(5)
    ])
    summary = run_notify(settings=capped, channel="telegram", now=NOW)
    assert summary.selected == 2
    assert summary.over_cap == 3
    assert route.call_count == 2
    # held jobs stay unmarked -> they alert on the next run
    second = run_notify(settings=capped, channel="telegram", now=NOW)
    assert second.selected == 2


def test_run_notify_feed_channel_counts_as_delivery(db: Settings) -> None:
    no_push = db.model_copy(update={"telegram_bot_token": "", "telegram_chat_id": ""})
    _seed(_job("pm", "Quant Intern", company="Polymarket", slug="polymarket"))
    summary = run_notify(settings=no_push, channel="feed", now=NOW)
    assert summary.sent["feed"] == 1
    assert summary.marked == 1
    assert no_push.feed_path.exists()


def test_run_notify_no_channels_configured_reports_error(db: Settings) -> None:
    no_push = db.model_copy(update={"telegram_bot_token": "", "telegram_chat_id": ""})
    _seed(_job("pm", "Quant Intern", company="Polymarket", slug="polymarket"))
    summary = run_notify(settings=no_push, channel="telegram", now=NOW)
    assert summary.marked == 0
    assert summary.errors and "no delivery channel" in summary.errors[0]


def test_duplicate_job_uids_alert_once(db: Settings) -> None:
    a = _job("dup", "Quant Intern", company="Polymarket", slug="polymarket")
    b = _job("dup", "Quant Intern", company="Polymarket", slug="polymarket")
    alerts = select_alerts([a, b], db, now=NOW)
    assert len(alerts) == 1
