from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.crt_sh import (
    _crtsh_url,
    careers_subdomains,
    discover_from_crtsh,
)
from internhunter.discovery.internship_lists import board_refs, entry_to_job
from internhunter.discovery.jsonld import discover_from_jsonld, extract_jobposting_urls
from internhunter.discovery.searxng import _ATS_HOSTS, _DEFAULT_QUERIES


# --- SearXNG dork breadth (A1) ---
def test_dorks_cover_all_ats_hosts() -> None:
    assert len(_DEFAULT_QUERIES) == len(_ATS_HOSTS)
    joined = "\n".join(_DEFAULT_QUERIES)
    for host in _ATS_HOSTS:
        assert f"site:{host}" in joined
    assert "co-op" in joined and "new grad" in joined and "early career" in joined


# --- crt.sh (A3) ---
def test_careers_subdomains_filters() -> None:
    rows = [
        {"name_value": "careers.acme.com\nwww.acme.com"},
        {"name_value": "jobs.acme.com"},
        {"name_value": "*.acme.com"},
        {"name_value": "blog.acme.com"},
    ]
    hosts = careers_subdomains(rows, "acme.com")
    assert "careers.acme.com" in hosts
    assert "jobs.acme.com" in hosts
    assert "www.acme.com" not in hosts
    assert "blog.acme.com" not in hosts


async def test_discover_from_crtsh_resolves_board(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_crtsh_url("acme.com")] = httpx.Response(
        200, text=json.dumps([{"name_value": "careers.acme.com"}])
    )
    # the careers page embeds a greenhouse board link
    ctx.responses["https://careers.acme.com"] = httpx.Response(
        200, text='<a href="https://boards.greenhouse.io/acmecorp">Jobs</a>'
    )
    dets = await discover_from_crtsh(ctx, "acme.com")
    assert ("greenhouse", "acmecorp") in {(d.ats, d.token) for d in dets}


# --- JSON-LD (A4) ---
def test_extract_jobposting_urls() -> None:
    html = """
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Intern","url":"https://jobs.lever.co/acme/123"}
    </script>
    """
    urls = extract_jobposting_urls(html)
    assert "https://jobs.lever.co/acme/123" in urls


def test_extract_jobposting_handles_graph() -> None:
    html = """
    <script type="application/ld+json">
    {"@graph":[{"@type":"WebPage"},{"@type":"JobPosting","url":"https://jobs.ashbyhq.com/acme/x"}]}
    </script>
    """
    assert "https://jobs.ashbyhq.com/acme/x" in extract_jobposting_urls(html)


async def test_discover_from_jsonld(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses["https://acme.com/careers"] = httpx.Response(
        200,
        text='<script type="application/ld+json">{"@type":"JobPosting","url":"https://boards.greenhouse.io/acme"}</script>',
    )
    dets = await discover_from_jsonld(ctx, "https://acme.com/careers")
    assert ("greenhouse", "acme") in {(d.ats, d.token) for d in dets}


# --- internship_lists alternate keys (A2) ---
def test_entry_to_job_alternate_keys() -> None:
    entry = {
        "role": "Software Intern",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "company": "Acme",
        "active": True,
    }
    job = entry_to_job(entry)
    assert job is not None
    assert job.title == "Software Intern"
    assert job.ats == "greenhouse"
    assert job.company == "Acme"


def test_board_refs_alternate_keys() -> None:
    entries = [
        {
            "role": "Intern",
            "application_link": "https://jobs.lever.co/beta/2",
            "organization": "Beta",
        },
    ]
    refs = board_refs(entries)
    assert ("lever", "beta") in {(r.ats, r.token) for r in refs}
