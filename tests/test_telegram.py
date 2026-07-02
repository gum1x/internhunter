from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from internhunter.core.db import Job
from internhunter.notify.telegram import build_telegram_message, send_telegram
from internhunter.referrals import Connection

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _job(**overrides: object) -> Job:
    values: dict[str, object] = dict(
        job_uid="j1",
        ats="ashby",
        board_token="polymarket",
        canonical_url="https://jobs.ashbyhq.com/polymarket/j1",
        url_hash="j1",
        company="Polymarket",
        company_slug="polymarket",
        title="Quant Research Intern",
        title_normalized="quant research intern",
        location_normalized="New York, NY",
        is_remote=False,
        posted_at=NOW - timedelta(hours=3),
        first_seen_at=NOW - timedelta(hours=1),
        discovery_score=0.91,
    )
    values.update(overrides)
    return Job(**values)  # type: ignore[arg-type]


def test_message_has_company_role_link_age_and_cold_flag() -> None:
    text = build_telegram_message(_job(), now=NOW)
    assert "Quant Research Intern" in text
    assert "Polymarket" in text
    assert "https://jobs.ashbyhq.com/polymarket/j1" in text
    assert "posted 3h ago" in text
    assert "❄️ Cold apply" in text


def test_message_flags_warm_intro_with_connection() -> None:
    conn = Connection(
        name="Pat Prediction",
        relationship="Polymarket research collaboration",
        contact="@pat",
    )
    text = build_telegram_message(_job(), conn, now=NOW)
    assert "🤝" in text
    assert "Pat Prediction" in text
    assert "Polymarket research collaboration" in text
    assert "@pat" in text
    assert "Cold apply" not in text


def test_message_escapes_html_in_title() -> None:
    job = _job(title="C++ <Intern> & Friends")
    text = build_telegram_message(job, now=NOW)
    assert "<Intern>" not in text
    assert "&lt;Intern&gt;" in text


def test_age_falls_back_to_first_seen() -> None:
    job = _job(posted_at=None, first_seen_at=NOW - timedelta(minutes=12))
    assert "posted 12m ago" in build_telegram_message(job, now=NOW)


def test_age_unknown_when_no_dates() -> None:
    job = _job(posted_at=None, first_seen_at=None)
    assert "age unknown" in build_telegram_message(job, now=NOW)


def test_age_days_for_old_postings() -> None:
    job = _job(posted_at=NOW - timedelta(days=5))
    assert "posted 5d ago" in build_telegram_message(job, now=NOW)


def test_naive_posted_at_treated_as_utc() -> None:
    job = _job(posted_at=(NOW - timedelta(hours=2)).replace(tzinfo=None))
    assert "posted 2h ago" in build_telegram_message(job, now=NOW)


def test_reasons_rendered() -> None:
    text = build_telegram_message(_job(), now=NOW, reasons=("target-firm:Polymarket",))
    assert "target-firm:Polymarket" in text


@respx.mock
def test_send_telegram_posts_to_bot_api() -> None:
    route = respx.post("https://api.telegram.org/botTOKEN/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    status = send_telegram("hello", "TOKEN", "12345")
    assert status == 200
    assert route.called
    body = route.calls.last.request.content
    assert b'"chat_id": "12345"' in body or b'"chat_id":"12345"' in body
    assert b"HTML" in body
