from __future__ import annotations

from pathlib import Path

from internhunter.config.settings import Settings
from internhunter.discovery.google_jobs import ingest_google_jobs
from internhunter.discovery.university import load_university_urls


def test_seed_university_list_loads() -> None:
    urls = load_university_urls()
    assert urls, "expected the bundled universities.jsonl seed to load"
    assert all(u.startswith("http") for u in urls)


def test_load_university_urls_custom_path(tmp_path: Path) -> None:
    p = tmp_path / "u.jsonl"
    p.write_text(
        '{"url": "https://a.edu/jobs", "name": "A"}\nnot-json\n{"name": "no url"}\n',
        encoding="utf-8",
    )
    assert load_university_urls(p) == ["https://a.edu/jobs"]


async def test_google_jobs_inert_without_searxng(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "t.db", cache_dir=tmp_path / "c", searxng_url="")
    assert await ingest_google_jobs(settings) == (0, 0, 0)
