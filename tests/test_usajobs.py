from __future__ import annotations

from internhunter.discovery.usajobs import parse_results

_HTML = """
<html><body>
<div class="usajobs-search-result--core">
  <a class="usajobs-search-result--core__title" href="/job/12345?abc=1">Student Trainee Intern</a>
  <span class="usajobs-search-result--core__agency">Department of Energy</span>
  <span class="usajobs-search-result--core__location">Washington, DC</span>
</div>
<div class="usajobs-search-result--core">
  <a class="usajobs-search-result--core__title" href="/job/67890">IT Intern</a>
  <span class="usajobs-search-result--core__department">NASA</span>
  <span class="usajobs-search-result--core__location">Houston, TX</span>
</div>
</body></html>
"""


def test_parse_results_extracts_jobs() -> None:
    jobs = parse_results(_HTML)
    assert len(jobs) == 2
    first = jobs[0]
    assert first.title == "Student Trainee Intern"
    assert first.company == "Department of Energy"
    assert first.url == "https://www.usajobs.gov/job/12345"
    assert first.location == "Washington, DC"
    assert first.source == "usajobs"
    assert jobs[1].company == "NASA"


def test_parse_results_empty_on_blank() -> None:
    assert parse_results("") == []
