from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from internhunter.core.db import Job
from internhunter.discovery import reresolve as rr


def _listing_job(url: str, uid: str) -> Job:
    now = datetime.now(UTC)
    return Job(
        job_uid=uid, ats="listing", board_token="", canonical_url=url,
        url_hash=f"h-{uid}", company="x", company_slug="x", title="Intern",
        title_normalized="intern", is_internship=True, description_text="",
        raw={}, first_seen_at=now, last_seen_at=now,
    )


async def test_reresolve_resolves_listings_and_dedups(
    db_session: Any, fake_fetch_context: Any, monkeypatch: Any
) -> None:
    # Two listing URLs fingerprint to the SAME greenhouse board (must dedup to one),
    # plus a distinct lever board. The HTML fetch 404s (fake) -> URL detection only.
    for j in (
        _listing_job("https://boards.greenhouse.io/acme", "g1"),
        _listing_job("https://job-boards.greenhouse.io/acme", "g2"),
        _listing_job("https://jobs.lever.co/foo", "l1"),
    ):
        db_session.add(j)
    db_session.commit()

    # reresolve_listings builds its own context + session internally; redirect both to doubles.
    @asynccontextmanager
    async def fake_build(settings: Any = None) -> Any:
        yield fake_fetch_context

    monkeypatch.setattr(rr, "build_fetch_context", fake_build)
    monkeypatch.setattr(rr, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(rr, "get_session", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr("internhunter.discovery.merge.get_session", lambda: db_session)
    # Isolate from the on-disk board registry: merge_boards otherwise reads it for the
    # "known" set and appends new boards to it, which would leak across test runs.
    monkeypatch.setattr("internhunter.discovery.merge.load_boards", lambda *a, **k: [])
    monkeypatch.setattr("internhunter.discovery.merge._append_registry", lambda refs: None)

    examined, new_boards = await rr.reresolve_listings(fake_fetch_context.settings)

    assert examined == 3  # three distinct listing URLs probed
    assert new_boards == 2  # greenhouse/acme (deduped across two URLs) + lever/foo


async def test_reresolve_stops_at_wall_clock_budget(
    db_session: Any, fake_fetch_context: Any, monkeypatch: Any
) -> None:
    # Every fetch hangs far longer than the budget -> the pass must return promptly having
    # examined nothing, rather than stalling discover-all.
    import asyncio

    for j in (
        _listing_job("https://slow.example.com/a", "a"),
        _listing_job("https://slow.example.com/b", "b"),
    ):
        db_session.add(j)
    db_session.commit()

    async def hang(*a: Any, **k: Any) -> str:
        await asyncio.sleep(30)
        return ""

    monkeypatch.setattr(fake_fetch_context, "get_text", hang)

    @asynccontextmanager
    async def fake_build(settings: Any = None) -> Any:
        yield fake_fetch_context

    monkeypatch.setattr(rr, "build_fetch_context", fake_build)
    monkeypatch.setattr(rr, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(rr, "get_session", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr("internhunter.discovery.merge.get_session", lambda: db_session)
    monkeypatch.setattr("internhunter.discovery.merge.load_boards", lambda *a, **k: [])
    monkeypatch.setattr("internhunter.discovery.merge._append_registry", lambda refs: None)

    tiny = fake_fetch_context.settings.model_copy(update={"reresolve_budget_seconds": 0.1})
    examined, new_boards = await asyncio.wait_for(rr.reresolve_listings(tiny), timeout=5)

    assert examined == 0  # nothing finished within the 0.1s budget
    assert new_boards == 0
