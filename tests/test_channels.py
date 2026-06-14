from __future__ import annotations

from internhunter.contacts.channels import classify_url, kind_for_provider
from internhunter.contacts.types import DiscoveredPerson


def test_classify_url() -> None:
    assert classify_url("https://x.com/jane") == "x"
    assert classify_url("https://twitter.com/jane") == "x"
    assert classify_url("https://www.linkedin.com/in/jane") == "linkedin"
    assert classify_url("https://github.com/jane") == "github"
    assert classify_url("https://bsky.app/profile/jane") == "bluesky"
    assert classify_url("https://hachyderm.io/@jane") == "mastodon"
    assert classify_url("https://janedoe.dev") == "site"


def test_kind_for_provider_trusts_provider() -> None:
    assert kind_for_provider("bluesky", "https://bsky.app/profile/x") == "bluesky"
    assert kind_for_provider("mastodon", "https://example.social/@x") == "mastodon"
    # unknown provider falls back to host classification
    assert kind_for_provider(None, "https://github.com/x") == "github"


def test_add_channel_dedupes() -> None:
    p = DiscoveredPerson(full_name="Jane Doe")
    p.add_channel("x", "https://x.com/jane", "gravatar", 85.0, "verified")
    p.add_channel("x", "https://x.com/jane/", "github", 90.0)  # same value normalized
    assert len(p.channels) == 1
    p.add_channel("github", "https://github.com/jane", "github", 90.0)
    assert len(p.channels) == 2
    p.add_channel("x", "", "noop")  # empty value ignored
    assert len(p.channels) == 2
