from __future__ import annotations

from internhunter.contacts.runner import _dedupe, _headcount_band
from internhunter.contacts.types import DiscoveredPerson


def test_headcount_band_from_job_count() -> None:
    assert _headcount_band(0) is None
    assert _headcount_band(1) == "tiny"
    assert _headcount_band(8) == "mid"
    assert _headcount_band(50) == "large"


def test_dedupe_merges_known_email() -> None:
    people = [
        DiscoveredPerson(full_name="Jane Doe", linkedin_url="https://linkedin.com/in/jane"),
        DiscoveredPerson(
            full_name="Jane Doe",
            linkedin_url="https://linkedin.com/in/jane",
            known_email="jane@acme.com",
        ),
    ]
    merged = _dedupe(people)
    assert len(merged) == 1
    assert merged[0].known_email == "jane@acme.com"
