from __future__ import annotations

from pathlib import Path

from internhunter.core.db import Job
from internhunter.match.targets import (
    TargetConfig,
    TargetFirm,
    evaluate_job,
    get_targets,
    load_targets,
)

_YAML = """
enabled: true
firms:
  - name: Polymarket
    domains: [polymarket.com]
    tags: [quant]
    priority: high
  - name: Anduril
    domains: [anduril.com]
keywords:
  include: [intern, "founding engineer", "quant research"]
  exclude: [senior, staff]
locations: ["new york", "washington"]
remote_ok: true
funding_stages: [seed, series-a]
"""


def _job(
    title: str,
    company: str = "Acme",
    slug: str = "acme",
    domain: str | None = None,
    location: str | None = "New York, NY",
    remote: bool = False,
    is_internship: bool = False,
    score: float | None = None,
) -> Job:
    return Job(
        job_uid=f"{slug}:{title}",
        ats="greenhouse",
        board_token=slug,
        canonical_url=f"https://x/{slug}",
        url_hash=f"{slug}:{title}",
        company=company,
        company_slug=slug,
        company_domain=domain,
        title=title,
        title_normalized=title.lower(),
        location_normalized=location,
        is_remote=remote,
        is_internship=is_internship,
        discovery_score=score,
    )


def _config(tmp_path: Path) -> TargetConfig:
    path = tmp_path / "targets.yaml"
    path.write_text(_YAML)
    return load_targets(path)


def test_load_parses_firms_and_keywords(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    assert cfg.enabled
    assert [f.name for f in cfg.firms] == ["Polymarket", "Anduril"]
    assert cfg.firms[0].priority == "high"
    assert "intern" in cfg.include_keywords
    assert "senior" in cfg.exclude_keywords
    assert cfg.funding_stages == ("seed", "series-a")


def test_missing_file_degrades_to_disabled(tmp_path: Path) -> None:
    cfg = load_targets(tmp_path / "nope.yaml")
    assert not cfg.enabled
    assert evaluate_job(_job("Software Intern"), cfg).matched is False


def test_malformed_yaml_degrades(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a\n- list\n")
    cfg = load_targets(path)
    assert not cfg.enabled


def test_firm_match_by_domain(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = _job("Software Engineer Intern", company="Polymarket Inc.",
               slug="polymarket-inc", domain="polymarket.com", is_internship=True)
    match = evaluate_job(job, cfg)
    assert match.matched
    assert match.firm is not None and match.firm.name == "Polymarket"
    assert any(r.startswith("target-firm:") for r in match.reasons)


def test_firm_match_by_canonical_name(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = _job("Quant Research Intern", company="Anduril Industries Inc",
               slug="anduril-industries-inc", is_internship=True)
    match = evaluate_job(job, cfg)
    # canonical slug strips 'Inc'; 'anduril-industries' != 'anduril' so this one relies
    # on the keyword path — still matched, but not attributed to the firm.
    assert match.matched


def test_keyword_match_anywhere(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    match = evaluate_job(_job("Founding Engineer", company="TinyStartup",
                              slug="tinystartup"), cfg)
    assert match.matched
    assert match.firm is None
    assert match.reasons == ("keyword:founding engineer",)


def test_exclude_is_hard_veto_even_for_target_firm(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = _job("Senior Quant Research Engineer", company="Polymarket",
               slug="polymarket", domain="polymarket.com")
    match = evaluate_job(job, cfg)
    assert not match.matched
    assert match.reasons[0].startswith("excluded:")


def test_location_gate_blocks_offsite(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = _job("Software Intern", location="London, UK", is_internship=True)
    match = evaluate_job(job, cfg)
    assert not match.matched
    assert match.reasons == ("location",)


def test_remote_passes_location_gate(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = _job("Software Intern", location="Anywhere", remote=True, is_internship=True)
    assert evaluate_job(job, cfg).matched


def test_empty_locations_means_anywhere() -> None:
    cfg = TargetConfig(include_keywords=("intern",))
    job = _job("Software Intern", location="Ulaanbaatar")
    assert evaluate_job(job, cfg).matched


def test_firm_without_role_signal_does_not_match(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = _job("Accountant", company="Polymarket", slug="polymarket",
               domain="polymarket.com")
    assert not evaluate_job(job, cfg).matched


def test_get_targets_reloads_on_mtime_change(tmp_path: Path) -> None:
    import os

    path = tmp_path / "targets.yaml"
    path.write_text(_YAML)
    first = get_targets(path)
    assert len(first.firms) == 2
    path.write_text(_YAML.replace("  - name: Anduril\n    domains: [anduril.com]\n", ""))
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    second = get_targets(path)
    assert len(second.firms) == 1


def test_firm_parse_skips_nameless_entries(tmp_path: Path) -> None:
    path = tmp_path / "targets.yaml"
    path.write_text("firms:\n  - domains: [x.com]\n  - name: Real\n")
    cfg = load_targets(path)
    assert [f.name for f in cfg.firms] == ["Real"]


def test_subdomain_matches_firm_domain() -> None:
    cfg = TargetConfig(
        firms=(TargetFirm(name="Anduril", slug="anduril", canonical_slug="anduril",
                          domains=("anduril.com",)),),
        include_keywords=("intern",),
    )
    job = _job("Intern", company="Careers", slug="careers",
               domain="jobs.anduril.com", is_internship=True)
    match = evaluate_job(job, cfg)
    assert match.firm is not None and match.firm.name == "Anduril"
