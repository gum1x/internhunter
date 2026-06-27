from __future__ import annotations

from typing import Any

import pytest

from internhunter.discovery.arbeitsagentur import parse_results as arbeit_parse
from internhunter.discovery.bluesky import parse_posts
from internhunter.discovery.crt_bulk import discover_from_crt_bulk, hosts_from_rows
from internhunter.discovery.eures import parse_vacancies
from internhunter.discovery.fingerprint import detect_from_url
from internhunter.discovery.idealist import parse_hits
from internhunter.discovery.reddit import _fetch_sub, parse_listing
from internhunter.discovery.web_data_commons import detections_from_nquads


def test_crt_bulk_hosts_and_detection() -> None:
    rows = [
        {"name_value": "acme.recruitee.com\n*.recruitee.com"},
        {"name_value": "beta.recruitee.com"},
        {"name_value": "unrelated.example.com"},
    ]
    hosts = hosts_from_rows(rows, "recruitee.com")
    assert hosts == ["acme.recruitee.com", "beta.recruitee.com"]
    det = detect_from_url(f"https://{hosts[0]}")
    assert det is not None and det.ats == "recruitee" and det.token == "acme"


def test_bluesky_parse_posts_uses_facet_link() -> None:
    data = {
        "posts": [
            {
                "record": {
                    "text": "Acme is hiring a Software Intern! apply here",
                    "createdAt": "2026-05-01T00:00:00Z",
                    "facets": [
                        {"features": [
                            {"$type": "app.bsky.richtext.facet#link",
                             "uri": "https://boards.greenhouse.io/acme/jobs/1"}
                        ]}
                    ],
                }
            }
        ]
    }
    jobs = parse_posts(data)
    assert len(jobs) == 1
    assert jobs[0].url == "https://boards.greenhouse.io/acme/jobs/1"
    assert jobs[0].source == "bluesky"


def test_reddit_parse_listing_filters_and_links() -> None:
    data = {
        "data": {
            "children": [
                {"data": {
                    "title": "Summer 2026 Software Engineering Intern",
                    "selftext": "Apply: https://jobs.lever.co/acme/9",
                    "url": "https://reddit.com/r/internships/comments/x",
                    "permalink": "/r/internships/comments/x",
                    "created_utc": 1700000000,
                }},
                {"data": {"title": "Rate my resume", "selftext": "help", "url": "https://x"}},
            ]
        }
    }
    jobs = parse_listing(data, "internships")
    assert len(jobs) == 1
    assert jobs[0].url == "https://jobs.lever.co/acme/9"
    assert jobs[0].source == "reddit:internships"


def test_eures_parse_vacancies() -> None:
    data = {"jvs": [
        {"id": "abc123", "title": "Marketing Internship",
         "employer": {"name": "Acme EU"}, "locationMap": {"DE": ["DE1"]},
         "creationDate": 1700000000000, "description": "join us"},
        {"title": "no id -> skipped"},
    ]}
    jobs = parse_vacancies(data)
    assert len(jobs) == 1
    assert jobs[0].company == "Acme EU"
    assert jobs[0].url == "https://europa.eu/eures/portal/jv-se/jv-details/abc123?lang=en"
    assert jobs[0].source == "eures"


def test_idealist_parse_hits() -> None:
    data = {"hits": [
        {"name": "Nonprofit Intern", "orgName": "Good Org",
         "url": {"en": "/en/internship/abc?x=1", "es": "/es/..."},
         "city": "New York", "stateStr": "NY", "country": "US",
         "published": 1700000000, "description": "help", "type": "INTERNSHIP",
         "objectID": "1"},
        {"name": "no url"},
    ]}
    jobs = parse_hits(data)
    assert len(jobs) == 1
    assert jobs[0].url == "https://www.idealist.org/en/internship/abc"
    assert jobs[0].company == "Good Org"
    assert jobs[0].location == "New York, NY, US"


def test_arbeitsagentur_parse_results() -> None:
    data = {"ergebnisliste": [
        {"stellenangebotsTitel": "Praktikant Software", "firma": "Acme GmbH",
         "referenznummer": "R1", "arbeitsort": {"ort": "Berlin"},
         "datumErsteVeroeffentlichung": "2026-05-01"},
        {"stellenangebotsTitel": "ext", "externeURL": "https://acme.de/apply", "firma": "X"},
    ]}
    jobs = arbeit_parse(data)
    assert len(jobs) == 2
    r1 = next(j for j in jobs if j.company == "Acme GmbH")
    assert r1.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/R1"
    assert r1.location == "Berlin"
    assert any(j.url == "https://acme.de/apply" for j in jobs)


async def test_reddit_pullpush_wrapper() -> None:
    # PullPush returns a flat {"data": [post,...]}; _fetch_sub must re-wrap it for parse_listing.
    class _Ctx:
        class logger:
            @staticmethod
            def debug(*a: object, **k: object) -> None: ...

        async def get_json(self, url: str, **kw: object) -> object:
            return {"data": [
                {"title": "Summer 2026 SWE Intern",
                 "selftext": "apply https://jobs.lever.co/acme/9",
                 "url": "https://reddit.com/r/x", "permalink": "/r/x",
                 "created_utc": 1700000000},
            ]}

    wrapped = await _fetch_sub(_Ctx(), "internships")  # type: ignore[arg-type]
    jobs = parse_listing(wrapped, "internships")
    assert len(jobs) == 1 and jobs[0].url == "https://jobs.lever.co/acme/9"


def test_web_data_commons_nquads_parse() -> None:
    lines = [
        '<http://x/job/1> <http://schema.org/applyUrl> '
        '<https://jobs.lever.co/acme/1> <http://x/> .',
        '<http://x/job/1> <http://schema.org/title> "Intern" <http://x/> .',  # no URL predicate
        '<http://y> <http://schema.org/url> "https://acme.recruitee.com" <http://y/> .',
    ]
    dets = detections_from_nquads(lines)
    pairs = {(d.ats, d.token) for d in dets}
    assert ("lever", "acme") in pairs
    assert ("recruitee", "acme") in pairs


@pytest.mark.parametrize(
    "url,ats,token",
    [
        ("https://acme.taleo.net/careersection/jobsearch.ftl", "taleo", "acme"),
        ("https://www.governmentjobs.com/careers/cityofaustin", "neogov", "cityofaustin"),
    ],
)
def test_longtail_ats_detectors(url: str, ats: str, token: str) -> None:
    det = detect_from_url(url)
    assert det is not None and det.ats == ats and det.token == token


async def test_crt_bulk_skips_infra_tokens(fake_fetch_context: Any) -> None:
    import httpx

    from internhunter.discovery.crt_bulk import _crtsh_url

    ctx = fake_fetch_context
    rows = [
        {"name_value": "acme.recruitee.com"},
        {"name_value": "s3.recruitee.com"},      # infra noise -> must be skipped
        {"name_value": "status.recruitee.com"},  # infra noise -> must be skipped
    ]
    ctx.responses[_crtsh_url("recruitee.com")] = httpx.Response(200, json=rows)
    dets = await discover_from_crt_bulk(ctx, domains=("recruitee.com",))
    tokens = {d.token for d in dets}
    assert "acme" in tokens
    assert "s3" not in tokens and "status" not in tokens
