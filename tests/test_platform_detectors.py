from __future__ import annotations

import pytest

from internhunter.discovery.fingerprint import detect_from_url


@pytest.mark.parametrize(
    "url,ats,token",
    [
        ("https://acme.eightfold.ai/careers", "eightfold", "acme"),
        ("https://acme.phenompeople.com/jobs", "phenom", "acme"),
        ("https://career5.successfactors.com/career?company=acme", "successfactors", "career5"),
        ("https://acme.successfactors.eu/", "successfactors", "acme"),
    ],
)
def test_detects_big_company_platforms(url: str, ats: str, token: str) -> None:
    detection = detect_from_url(url)
    assert detection is not None
    assert detection.ats == ats
    assert detection.token == token


def test_platform_sources_are_registered() -> None:
    # importing the package triggers @register_source for the new tier-c adapters
    import internhunter.sources.tier_c  # noqa: F401
    from internhunter.sources.base import SOURCE_REGISTRY

    for ats in ("eightfold", "phenom", "successfactors"):
        assert ats in SOURCE_REGISTRY
