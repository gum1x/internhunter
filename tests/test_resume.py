from __future__ import annotations

import pytest

from internhunter.resume.tailor import (
    ATS_FORMAT_NOTES,
    TRUTHFULNESS_CONTRACT,
    TailorRequest,
    TailorResult,
    tailor_resume,
)


def test_truthfulness_contract_is_nonempty_and_guards() -> None:
    assert isinstance(TRUTHFULNESS_CONTRACT, str)
    assert TRUTHFULNESS_CONTRACT.strip()
    lowered = TRUTHFULNESS_CONTRACT.lower()
    assert "truthful" in lowered
    assert "never" in lowered


def test_ats_format_notes_is_nonempty_and_mentions_ats() -> None:
    assert isinstance(ATS_FORMAT_NOTES, str)
    assert ATS_FORMAT_NOTES.strip()
    assert "ATS" in ATS_FORMAT_NOTES


def test_tailor_request_and_result_construct() -> None:
    request = TailorRequest(
        job_uid="j1",
        job_text="backend python internship",
        base_resume="resume body",
        profile="profile body",
    )
    assert request.job_uid == "j1"
    assert request.job_text == "backend python internship"
    assert request.base_resume == "resume body"
    assert request.profile == "profile body"

    result = TailorResult(
        tailored_resume="tailored",
        changed_sections=["Experience"],
        warnings=[],
    )
    assert result.tailored_resume == "tailored"
    assert result.changed_sections == ["Experience"]
    assert result.warnings == []


def test_tailor_resume_returns_result() -> None:
    class _FakeBackend:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, system=None, max_tokens=1024):
            self.calls += 1
            if self.calls == 1:
                return "y"  # tailor response
            else:
                return "[]"  # verify response: clean

    request = TailorRequest(
        job_uid="j1",
        job_text="x",
        base_resume="y",
        profile="z",
    )
    result = tailor_resume(request, _FakeBackend())
    assert isinstance(result, TailorResult)
