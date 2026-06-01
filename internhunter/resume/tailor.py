from __future__ import annotations

from dataclasses import dataclass

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


def tailor_resume(request: TailorRequest) -> TailorResult:
    raise NotImplementedError(
        "resume tailoring is stubbed; see TRUTHFULNESS_CONTRACT"
    )
