from __future__ import annotations

from internhunter.contacts.email.registries import parse_npm, parse_pypi
from internhunter.contacts.people.searxng_people import parse_social_result


def test_parse_npm() -> None:
    data = {
        "author": {"name": "Sindre", "email": "sindre@gmail.com"},
        "maintainers": [{"name": "bob", "email": "bob@example.com"}, {"name": "noemail"}],
    }
    pairs = parse_npm(data)
    assert ("Sindre", "sindre@gmail.com") in pairs
    assert ("bob", "bob@example.com") in pairs
    assert len(pairs) == 2


def test_parse_pypi_strips_angle_brackets() -> None:
    data = {"info": {"author": "Kenneth", "author_email": "Kenneth Reitz <me@kennethreitz.org>"}}
    pairs = parse_pypi(data)
    assert ("Kenneth", "me@kennethreitz.org") in pairs


def test_parse_social_result_classifies_channel() -> None:
    p = parse_social_result("Jane Doe (@janedoe) · GitHub", "https://github.com/janedoe")
    assert p is not None
    assert p.full_name == "Jane Doe"
    assert any(c["kind"] == "github" for c in p.channels)


def test_parse_social_result_skips_generic_site() -> None:
    assert parse_social_result("Some Blog", "https://randomblog.com/post") is None
