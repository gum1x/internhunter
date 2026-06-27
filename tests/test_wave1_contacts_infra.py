from __future__ import annotations

import sys
import types

import httpx
import pytest

from internhunter.contacts.people import git_commits
from internhunter.core import fetch as fetchmod
from internhunter.discovery import board_resolve


def test_board_resolve_via_cname(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chain(host: str, max_hops: int = 5) -> list[str]:
        return ["acme.recruitee.com"] if host == "careers.acme.com" else []

    monkeypatch.setattr(board_resolve, "_cname_chain", fake_chain)
    dets = board_resolve.resolve_domain_boards("acme.com")
    assert ("recruitee", "acme") in {(d.ats, d.token) for d in dets}


def test_git_commits_filters_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git_commits, "_repo_clone_urls", lambda *a, **k: ["https://x/r.git"])
    monkeypatch.setattr(
        git_commits, "_authors",
        lambda url: [("Jane", "jane@acme.com"), ("Ext", "ext@other.com"),
                     ("Bot", "bot@users.noreply.github.com")],
    )
    people = git_commits.discover_people_git_commits("acme", "acme.com")
    assert [p.known_email for p in people] == ["jane@acme.com"]
    assert people[0].person_source == "git_commit"


def test_curl_cffi_fallback_builds_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CffiResp:
        status_code = 200
        content = b"hello"
        headers = {"content-type": "text/plain"}

    fake_requests = types.SimpleNamespace(get=lambda *a, **k: _CffiResp())
    fake_pkg = types.ModuleType("curl_cffi")
    fake_pkg.requests = fake_requests  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_pkg)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_requests)

    resp = fetchmod._curl_cffi_get("https://blocked.example/x", None, {})
    assert isinstance(resp, httpx.Response)
    assert resp.status_code == 200
    assert resp.content == b"hello"
