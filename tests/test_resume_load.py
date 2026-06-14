from __future__ import annotations

from typing import Any

from internhunter.config.settings import Settings
from internhunter.match.prefilter import load_candidate_profile
from internhunter.resume.load import load_resume_text


def test_load_resume_txt(tmp_path: Any) -> None:
    (tmp_path / "resume.txt").write_text("Ryan built a trading bot in Python.")
    assert load_resume_text(tmp_path / "resume.txt") == "Ryan built a trading bot in Python."


def test_load_resume_by_stem_prefers_md(tmp_path: Any) -> None:
    (tmp_path / "resume.md").write_text("# Ryan\nReact + Flutter apps")
    text = load_resume_text(tmp_path / "resume")  # stem -> finds resume.md
    assert text is not None and "Flutter" in text


def test_load_resume_missing_returns_none(tmp_path: Any) -> None:
    assert load_resume_text(tmp_path / "nope") is None


def test_candidate_profile_merges_resume(tmp_path: Any) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text("name: Ryan\nskills:\n  - python\n")
    (tmp_path / "resume.txt").write_text("Led growth at a fintech startup.")
    settings = Settings(profile_path=profile, resume_path=tmp_path / "resume.txt")
    merged = load_candidate_profile(settings)
    assert "python" in merged
    assert "RÉSUMÉ" in merged
    assert "fintech startup" in merged


def test_candidate_profile_without_resume(tmp_path: Any) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text("name: Ryan\nskills:\n  - python\n")
    settings = Settings(profile_path=profile, resume_path=tmp_path / "absent")
    merged = load_candidate_profile(settings)
    assert "python" in merged
    assert "RÉSUMÉ" not in merged
