from __future__ import annotations

import pytest

from internhunter.discovery.fingerprint import detect_from_html, detect_from_url


@pytest.mark.parametrize(
    "url,ats,token",
    [
        ("https://boards.greenhouse.io/stripe", "greenhouse", "stripe"),
        ("https://boards.greenhouse.io/embed/job_board?for=airbnb", "greenhouse", "airbnb"),
        ("https://job-boards.greenhouse.io/databricks/jobs/123", "greenhouse", "databricks"),
        ("https://jobs.lever.co/netflix", "lever", "netflix"),
        ("https://api.lever.co/v0/postings/spotify", "lever", "spotify"),
        ("https://jobs.ashbyhq.com/openai", "ashby", "openai"),
        ("https://api.ashbyhq.com/posting-api/job-board/linear", "ashby", "linear"),
        ("https://jobs.smartrecruiters.com/Bosch", "smartrecruiters", "Bosch"),
        ("https://api.smartrecruiters.com/v1/companies/Acme/postings", "smartrecruiters", "Acme"),
        ("https://apply.workable.com/sumup/", "workable", "sumup"),
        ("https://acme.recruitee.com/", "recruitee", "acme"),
        ("https://shop.jobs.personio.de/", "personio", "shop"),
        ("https://acme.breezy.hr/json", "breezy", "acme"),
        ("https://acme.applytojob.com/apply", "jazzhr", "acme"),
        ("https://acme.bamboohr.com/careers/list", "bamboohr", "acme"),
        ("https://acme.rippling-ats.com/jobs", "rippling", "acme"),
        ("https://acme.zohorecruit.com/jobs/Careers", "zohorecruit", "acme"),
        ("https://jobs.jobvite.com/careers/acme/jobs", "jobvite", "acme"),
        ("https://jobs.dover.com/companies/acme", "dover", "acme"),
        ("https://acme.wd1.myworkdayjobs.com/en-US/careers", "workday", "acme"),
        ("https://careers.icims.com/jobs/12345/intern/job", "icims", "12345"),
        ("https://jobs.adp.com/company/acme", "adp", "acme"),
        ("https://recruiting.ultipro.com/ACM1001/JobBoard/abc/Jobs.xml", "ultipro", "ACM1001"),
        ("https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience/", "oracle_cloud", "acme"),
    ],
)
def test_detect_from_url(url: str, ats: str, token: str) -> None:
    detection = detect_from_url(url)
    assert detection is not None
    assert detection.ats == ats
    assert detection.token == token


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/careers",
        "https://boards.greenhouse.io/embed/job_board",
        "https://www.lever.co/",
        "https://jobs.ashbyhq.com/",
        "not a url",
    ],
)
def test_detect_from_url_rejects_non_boards(url: str) -> None:
    assert detect_from_url(url) is None


def test_detect_from_html_finds_embedded_boards() -> None:
    html = """
    <html><body>
      <iframe src="https://boards.greenhouse.io/embed/job_board?for=figma"></iframe>
      <a href="https://jobs.lever.co/ramp">careers</a>
      <a href="https://jobs.lever.co/ramp">dup</a>
      <script>fetch('https://api.ashbyhq.com/posting-api/job-board/vercel')</script>
    </body></html>
    """
    detections = detect_from_html(html)
    pairs = {(d.ats, d.token) for d in detections}
    assert ("greenhouse", "figma") in pairs
    assert ("lever", "ramp") in pairs
    assert ("ashby", "vercel") in pairs
    assert len(detections) == 3
