from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.etree.ElementTree import fromstring

from internhunter.core.db import Job
from internhunter.notify.discord import build_discord_payload
from internhunter.notify.email import build_email
from internhunter.notify.feed import build_feed, write_feed
from internhunter.notify.ntfy import build_ntfy_message
from internhunter.notify.select import select_notifiable

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _job(
    uid: str,
    title: str,
    discovery_score: float | None = None,
    deadline_at: datetime | None = None,
) -> Job:
    return Job(
        job_uid=uid,
        ats="greenhouse",
        board_token="acme",
        canonical_url=f"https://x/{uid}",
        url_hash=uid,
        company="Acme",
        company_slug="acme",
        title=title,
        title_normalized=title.lower(),
        location_normalized="Remote",
        discovery_score=discovery_score,
        deadline_at=deadline_at,
        posted_at=NOW,
    )


def test_select_filters_by_fit_and_deadline() -> None:
    high = _job("h", "high fit", discovery_score=0.9)
    low = _job("l", "low fit", discovery_score=0.3)
    soon = _job("s", "deadline soon", deadline_at=NOW + timedelta(days=3))
    far = _job("f", "deadline far", deadline_at=NOW + timedelta(days=60))
    past = _job("p", "deadline past", deadline_at=NOW - timedelta(days=1))

    result = select_notifiable([low, high, soon, far, past], min_fit=0.6, now=NOW)

    uids = {j.job_uid for j in result}
    assert uids == {"h", "s"}


def test_select_dedupes_by_job_uid() -> None:
    one = _job("dup", "first instance", discovery_score=0.9)
    two = _job("dup", "second instance", discovery_score=0.9)
    result = select_notifiable([one, two], min_fit=0.6, now=NOW)
    assert len(result) == 1


def test_select_stable_order_by_score_desc() -> None:
    a = _job("a", "a", discovery_score=0.7)
    b = _job("b", "b", discovery_score=0.95)
    c = _job("c", "c", discovery_score=0.8)
    result = select_notifiable([a, b, c], min_fit=0.6, now=NOW)
    assert [j.job_uid for j in result] == ["b", "c", "a"]


def test_select_dedupes() -> None:
    job = _job("d", "dup", discovery_score=0.9)
    result = select_notifiable([job, job], now=NOW)
    assert len(result) == 1


def test_build_discord_payload() -> None:
    job = _job("h", "ML Intern", discovery_score=0.9)
    payload = build_discord_payload([job])
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["title"] == "ML Intern"
    assert embed["url"] == "https://x/h"
    names = {f["name"] for f in embed["fields"]}
    assert "Company" in names


def test_build_ntfy_message() -> None:
    job = _job("h", "ML Intern", discovery_score=0.9)
    message = build_ntfy_message([job])
    assert "ML Intern" in message
    assert "https://x/h" in message


def test_build_email() -> None:
    jobs = [_job("a", "Intern A"), _job("b", "Intern B")]
    message = build_email(jobs, "from@x.com", "to@x.com")
    assert "2" in str(message["Subject"])
    body = message.get_body(("plain",))
    assert body is not None
    content = body.get_content()
    assert "Intern A" in content
    assert "Intern B" in content


def test_build_feed_parseable() -> None:
    jobs = [_job("a", "Intern A"), _job("b", "Intern B")]
    xml = build_feed(jobs)
    root = fromstring(xml)
    items = root.findall("./channel/item")
    assert len(items) == 2
    titles = {item.findtext("title") for item in items}
    assert titles == {"Intern A", "Intern B"}


def test_write_feed(tmp_path: Path) -> None:
    jobs = [_job("a", "Intern A")]
    path = tmp_path / "feed.xml"
    write_feed(jobs, path)
    root = fromstring(path.read_text())
    assert len(root.findall("./channel/item")) == 1
