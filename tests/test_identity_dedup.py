from __future__ import annotations

from internhunter.contacts.dedup import merge_people
from internhunter.contacts.types import DiscoveredPerson


def test_merges_person_across_sources() -> None:
    # same person: LinkedIn-only record + GitHub-only record linked by a shared email
    a = DiscoveredPerson(full_name="Jane Doe", linkedin_url="https://linkedin.com/in/jane",
                         known_email="jane@acme.com")
    b = DiscoveredPerson(full_name="Jane Doe", github_login="janedoe",
                         known_email="jane@acme.com")
    merged = merge_people([a, b])
    assert len(merged) == 1
    assert merged[0].linkedin_url and merged[0].github_login  # both ids carried over


def test_merges_via_verified_channel() -> None:
    a = DiscoveredPerson(full_name="Jane Doe", linkedin_url="https://linkedin.com/in/jane")
    a.add_channel("x", "https://x.com/jane", "gravatar", 85.0, "verified")
    b = DiscoveredPerson(full_name="Jane Doe", github_login="jd")
    b.add_channel("x", "https://x.com/jane/", "github_social", 85.0, "verified")
    assert len(merge_people([a, b])) == 1


def test_does_not_merge_conflicting_logins() -> None:
    # two "John Smith"s with DIFFERENT github logins must stay separate
    a = DiscoveredPerson(full_name="John Smith", github_login="jsmith1")
    b = DiscoveredPerson(full_name="John Smith", github_login="jsmith2")
    assert len(merge_people([a, b])) == 2


def test_name_only_records_merge() -> None:
    a = DiscoveredPerson(full_name="Jane Doe", title="Recruiter")
    b = DiscoveredPerson(full_name="Jane Doe")
    assert len(merge_people([a, b])) == 1


def test_distinct_people_stay_separate() -> None:
    a = DiscoveredPerson(full_name="Jane Doe", github_login="jane")
    b = DiscoveredPerson(full_name="Bob Lee", github_login="bob")
    assert len(merge_people([a, b])) == 2
