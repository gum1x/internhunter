from __future__ import annotations

import json

import pytest

from internhunter.discovery.bluesky import parse_posts
from internhunter.discovery.crt_bulk import hosts_from_rows
from internhunter.discovery.eures import parse_vacancies
from internhunter.discovery.fingerprint import detect_from_url
from internhunter.discovery.jsonld_listings import listings_from_html
from internhunter.discovery.reddit import parse_listing
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
        {"title": "Data Intern", "jvUrl": "https://example.eu/jobs/1",
         "employer": {"name": "Acme EU"}, "creationDate": "2026-05-01"},
        {"title": "no url here"},
    ]}
    jobs = parse_vacancies(data)
    assert len(jobs) == 1
    assert jobs[0].company == "Acme EU"
    assert jobs[0].source == "eures"


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


def test_jsonld_listings_extract() -> None:
    markup = """
    <script type="application/ld+json">
    {"@type": "JobPosting", "title": "Nonprofit Intern",
     "url": "https://www.idealist.org/en/internship/abc",
     "hiringOrganization": {"name": "Good Org"},
     "jobLocation": {"address": {"addressLocality": "NYC", "addressRegion": "NY"}},
     "datePosted": "2026-05-01"}
    </script>
    """
    jobs = listings_from_html(markup, "idealist")
    assert len(jobs) == 1
    assert jobs[0].title == "Nonprofit Intern"
    assert jobs[0].company == "Good Org"
    assert jobs[0].location == "NYC, NY"


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


def test_eures_payload_shape() -> None:
    # guard against accidental key drift in the request body builder
    from internhunter.discovery.eures import _body

    body = _body(2, 50)
    assert body["page"] == 2 and body["resultsPerPage"] == 50
    assert body["keywords"][0]["keyword"] == "intern"
    json.dumps(body)  # must be JSON-serializable
