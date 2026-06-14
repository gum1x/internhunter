from __future__ import annotations

from internhunter.contacts.email.finder import find_email
from internhunter.contacts.email.infer import infer_pattern, templates_matching
from internhunter.contacts.email.permute import (
    normalize_token,
    permutations,
    split_name,
)
from internhunter.contacts.types import DiscoveredPerson


def test_normalize_strips_accents_and_punctuation() -> None:
    assert normalize_token("José") == "jose"
    assert normalize_token("O'Brien") == "obrien"
    assert normalize_token("Müller") in {"muller", "mueller"}


def test_split_name_handles_multipart() -> None:
    assert split_name("John Smith") == ("John", "Smith")
    assert split_name("Anne-Marie García López") == ("Anne-Marie", "López")
    assert split_name("Cher") is None


def test_permutations_ordered_and_unique() -> None:
    perms = permutations("John", "Smith", "apple.com")
    assert perms[0] == "john.smith@apple.com"
    assert "jsmith@apple.com" in perms
    assert len(perms) == len(set(perms))


def test_infer_pattern_locks_dominant_template() -> None:
    pairs = [
        ("John Smith", "jsmith@acme.com"),
        ("Jane Doe", "jdoe@acme.com"),
        ("Bob Lee", "blee@acme.com"),
    ]
    inf = infer_pattern(pairs, "acme.com")
    assert inf.template == "{f}{last}"
    assert inf.votes == 3


def test_infer_pattern_ignores_other_domains() -> None:
    pairs = [("John Smith", "jsmith@other.com")]
    inf = infer_pattern(pairs, "acme.com")
    assert inf.template is None


def test_templates_matching_finds_format() -> None:
    matches = templates_matching("John Smith", "john.smith@acme.com", "acme.com")
    assert "{first}.{last}" in matches


def test_find_email_prefers_github_known_email() -> None:
    person = DiscoveredPerson(full_name="Al Engineer", known_email="al@acme.com")
    result = find_email(person, "acme.com")
    assert result.email == "al@acme.com"
    assert result.email_status == "github"
    assert result.confidence >= 60


def test_find_email_uses_locked_template() -> None:
    person = DiscoveredPerson(full_name="Alice Wong", title="Recruiter")
    result = find_email(person, "acme.com", locked_template="{f}{last}")
    assert result.email == "awong@acme.com"


def test_find_email_scraped_match_beats_guess() -> None:
    person = DiscoveredPerson(full_name="Carol Ng")
    result = find_email(person, "acme.com", scraped_emails=["carol.ng@acme.com"])
    assert result.email == "carol.ng@acme.com"
    assert result.email_status == "scraped"
    # scraped alone = 70 -> "probable"; "verified" (>=85) needs an extra signal (holehe).
    assert result.label == "probable"


def test_find_email_falls_back_to_prior() -> None:
    person = DiscoveredPerson(full_name="Dan Park")
    result = find_email(person, "acme.com", headcount_band="large")
    assert result.email == "dan.park@acme.com"
    assert result.email_source.startswith("prior:")


async def test_m365_resolve_finds_confirmed_mailbox(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import internhunter.contacts.email.verify_m365 as m

    async def fake_confirms(email: str, wait: float = 12.0) -> bool | None:
        return email == "jane.doe@acme.com"

    monkeypatch.setattr(m, "m365_confirms", fake_confirms)
    got = await m.m365_resolve("Jane Doe", "acme.com")
    assert got == "jane.doe@acme.com"


async def test_m365_resolve_none_when_no_mailbox(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import internhunter.contacts.email.verify_m365 as m

    async def fake_confirms(email: str, wait: float = 12.0) -> bool | None:
        return False

    monkeypatch.setattr(m, "m365_confirms", fake_confirms)
    assert await m.m365_resolve("Jane Doe", "acme.com") is None


async def test_harvest_searxng_emails(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    import json
    from urllib.parse import urlencode

    import httpx

    from internhunter.contacts.email.harvest import harvest_searxng_emails

    ctx = fake_fetch_context
    url = "http://sx/search?" + urlencode({"q": '"@acme.com"', "format": "json"})
    ctx.responses[url] = httpx.Response(
        200,
        text=json.dumps(
            {
                "results": [
                    {
                        "title": "Contact us",
                        "content": "reach jane.doe@acme.com or bob@acme.com",
                        "url": "https://acme.com/contact",
                    }
                ]
            }
        ),
    )
    emails = await harvest_searxng_emails(ctx, "http://sx", "acme.com")
    assert "jane.doe@acme.com" in emails
    assert "bob@acme.com" in emails
