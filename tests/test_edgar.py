from __future__ import annotations

from typing import Any

from internhunter.discovery import edgar
from internhunter.discovery.edgar import _adsh_from_id, discover_from_edgar

_FORM_D = """<?xml version="1.0"?>
<edgarSubmission>
  <entityName>Acme Robotics Inc</entityName>
  <industryGroupType>Technology</industryGroupType>
  <relatedPersonName><firstName>Jane</firstName><lastName>Doe</lastName></relatedPersonName>
</edgarSubmission>
"""


def test_adsh_requires_18_digits() -> None:
    assert _adsh_from_id("0001234567-25-000123:primary_doc.xml") == "000123456725000123"
    # too short / non-numeric accession numbers are rejected
    assert _adsh_from_id("123-25-1:primary_doc.xml") is None
    assert _adsh_from_id("abc-de-fghij:primary_doc.xml") is None
    assert _adsh_from_id("") is None


async def test_cik_zero_padded_to_ten_digits(
    fake_fetch_context: Any, monkeypatch: Any
) -> None:
    ctx = fake_fetch_context
    requested: list[str] = []

    # EDGAR archive paths use a 10-digit zero-padded CIK; capture the URL the code builds.
    async def fake_get_text(url: str, **kwargs: Any) -> str:
        requested.append(url)
        return _FORM_D

    async def fake_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "0000320193-25-000010:primary_doc.xml",
                        "_source": {"ciks": ["0000320193"], "file_date": "2026-06-01"},
                    }
                ]
            }
        }

    # Avoid network resolution of guessed company domains.
    async def fake_resolve_many(_ctx: Any, _sites: list[str]) -> list[Any]:
        return []

    monkeypatch.setattr(ctx, "get_text", fake_get_text)
    monkeypatch.setattr(ctx, "get_json", fake_get_json)
    monkeypatch.setattr(edgar, "resolve_many", fake_resolve_many)

    await discover_from_edgar(ctx)

    assert requested == [
        "https://www.sec.gov/Archives/edgar/data/0000320193/000032019325000010/primary_doc.xml"
    ]
