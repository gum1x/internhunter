from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

TRUTHFULNESS_CONTRACT: str = (
    "Resume tailoring may reorder, rephrase, and emphasize existing true "
    "experience to match a target job.\n"
    "It must NEVER invent employers, titles, dates, credentials, skills, or "
    "metrics the candidate does not have.\n"
    "Every tailored bullet must trace directly back to a real source bullet "
    "in the base resume.\n"
    "When in doubt, prefer omission over fabrication: truthfulness is "
    "non-negotiable."
)

ATS_FORMAT_NOTES: str = (
    "Produce plain-text, single-column layout for ATS compatibility.\n"
    "Use standard section headings (Experience, Education, Skills, Projects).\n"
    "No tables, images, text-boxes, columns, or graphics.\n"
    "Export as .docx or .pdf that is machine-parseable."
)


@dataclass(frozen=True)
class TailorRequest:
    job_uid: str
    job_text: str
    base_resume: str
    profile: str


@dataclass(frozen=True)
class TailorResult:
    tailored_resume: str
    changed_sections: list[str]
    warnings: list[str]


def build_tailor_prompt(request: TailorRequest) -> str:
    return (
        f"{TRUTHFULNESS_CONTRACT}\n\n{ATS_FORMAT_NOTES}\n\n"
        f"TARGET JOB:\n{request.job_text}\n\n"
        f"CANDIDATE PROFILE:\n{request.profile}\n\n"
        f"BASE RESUME (the only source of truth):\n{request.base_resume}\n\n"
        "Rewrite the resume to emphasize the experience most relevant to the target job. "
        "Output ONLY the tailored resume text."
    )


def build_verify_prompt(base_resume: str, tailored: str) -> str:
    return (
        "You are an auditor. List every claim in the TAILORED resume that does NOT trace "
        "to a fact in the BASE resume (invented employers, titles, dates, metrics, skills). "
        'Reply with a JSON array of strings; reply "[]" if every claim is traceable.\n\n'
        f"BASE:\n{base_resume}\n\nTAILORED:\n{tailored}"
    )


def verify_truthful(
    base_resume: str, tailored: str, backend: Any, *, max_tokens: int = 512
) -> list[str]:
    reply = backend.generate(build_verify_prompt(base_resume, tailored), max_tokens=max_tokens)
    start, end = reply.find("["), reply.rfind("]")
    if start == -1 or end == -1:
        return ["verification failed: unparseable auditor reply"]
    try:
        items = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return ["verification failed: unparseable auditor reply"]
    return [str(x) for x in items] if isinstance(items, list) else []


def tailor_resume(request: TailorRequest, backend: Any, *, max_tokens: int = 1024) -> TailorResult:
    tailored = backend.generate(build_tailor_prompt(request), max_tokens=max_tokens).strip()
    problems = verify_truthful(request.base_resume, tailored, backend)
    if problems:
        return TailorResult(
            tailored_resume=request.base_resume,
            changed_sections=[],
            warnings=[f"reverted to base resume; unverifiable claims: {problems}"],
        )
    return TailorResult(tailored_resume=tailored, changed_sections=[], warnings=[])
