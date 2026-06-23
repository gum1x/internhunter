from __future__ import annotations

from pathlib import Path

from internhunter.config.settings import Settings
from internhunter.discovery.handshake import ingest_handshake
from internhunter.discovery.handshake import parse_cards as hs_parse
from internhunter.discovery.indeed import ingest_indeed
from internhunter.discovery.indeed import parse_cards as indeed_parse

_INDEED = """
<div class="job_seen_beacon">
  <h2 class="jobTitle"><a class="jcs-JobTitle" href="/rc/clk?jk=abc">Software Intern</a></h2>
  <span data-testid="company-name">Acme</span>
  <div data-testid="text-location">Austin, TX</div>
</div>
"""


def test_indeed_parse_cards() -> None:
    cards = indeed_parse(_INDEED)
    assert len(cards) == 1
    assert cards[0].title == "Software Intern"
    assert cards[0].company == "Acme"
    assert cards[0].url == "https://www.indeed.com/rc/clk"
    assert cards[0].source == "indeed"


async def test_ingest_indeed_inert_when_disabled(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "t.db", cache_dir=tmp_path / "c", enable_indeed=False)
    assert await ingest_indeed(settings) == (0, 0, 0)


async def test_ingest_handshake_inert_without_session(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "t.db",
        cache_dir=tmp_path / "c",
        handshake_session=tmp_path / "missing.json",
    )
    assert await ingest_handshake(settings) == (0, 0, 0)


def test_handshake_parse_cards_smoke() -> None:
    markup = '<a href="/stu/jobs/55"><div class="title">Data Intern</div></a>'
    cards = hs_parse(markup)
    assert cards and cards[0].url == "https://app.joinhandshake.com/stu/jobs/55"
