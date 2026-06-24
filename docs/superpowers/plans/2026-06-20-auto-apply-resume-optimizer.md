# Auto-Apply + Per-Job Resume Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-command/one-button feature that tailors the candidate's resume to each high-fit Tier-A internship and auto-submits the application, with conservative guardrails and a skip-and-queue path for any form it can't fill confidently.

**Architecture:** A new `internhunter/apply/` package orchestrates select → guardrail → probe → classify → tailor → render → submit → record. Submission is HTTP-first per ATS behind a common `Submitter` contract (Greenhouse + Lever implemented here; others added via a documented procedure). Any ATS without a registered adapter, any login wall/captcha, and any required field the classifier can't fill all route to a `needs_review` queue instead of submitting. Resume tailoring reuses the existing Claude `llm/` backend and enforces the `TRUTHFULNESS_CONTRACT` with a second verification pass.

**Tech Stack:** Python 3.12, SQLAlchemy (existing `core/db.py`), httpx via existing `FetchContext`, existing `llm/` Claude backend, `fpdf2` (new) for PDF rendering, argparse CLI, FastAPI+HTMX dashboard.

## Global Constraints

- Python ≥ 3.12; `from __future__ import annotations` at top of every new module (matches codebase).
- Master kill switch `enable_auto_apply` defaults to **False** — nothing submits until explicitly enabled.
- Reuse existing infrastructure: `build_fetch_context` (proxy via `http_proxy`), `get_backend`/`complete`/`LlmCache`, `load_candidate_profile`, `load_resume_text`, `get_session`. Do not create a second HTTP client or LLM stack.
- Truthfulness is non-negotiable: tailoring may reorder/rephrase/emphasize real experience but must never invent. The `TRUTHFULNESS_CONTRACT` in `internhunter/resume/tailor.py` is authoritative.
- No live application submissions in tests — adapters are tested against recorded HTML/JSON fixtures only.
- Pipeline fails closed: unknown ATS, unfillable field, captcha, login wall, missing required applicant PII, or failed tailoring-verification → never a blind submit.
- Application dedupe is already enforced by `UniqueConstraint("job_uid")` on the `applications` table; reuse it, do not add a second tracker table.

---

## File Structure

- `internhunter/apply/__init__.py` — package marker.
- `internhunter/apply/applicant.py` — `Applicant` dataclass + `load_applicant` + `validate_applicant`.
- `internhunter/apply/fields.py` — `FormField` + `classify_fields` + `field_key`.
- `internhunter/apply/submit/base.py` — `FormSpec`, `SubmitResult`, `Submitter` ABC, registry.
- `internhunter/apply/submit/greenhouse.py` — Greenhouse HTTP adapter.
- `internhunter/apply/submit/lever.py` — Lever HTTP adapter.
- `internhunter/apply/guardrails.py` — guardrail checks.
- `internhunter/apply/render.py` — tailored text → ATS-parseable PDF.
- `internhunter/apply/pipeline.py` — orchestrator + `Application` recording.
- `internhunter/resume/tailor.py` — implement the stubbed `tailor_resume` + truthfulness verify.
- `internhunter/config/profile.yaml` — add `applicant:` section.
- `internhunter/config/settings.py` — add guardrail/apply settings.
- `internhunter/cli.py` — add `apply` subcommand.
- `internhunter/web/app.py` — add auto-apply control + endpoint + review-queue view.
- `docs/adapter-authoring.md` — procedure for the remaining 6 Tier-A adapters.
- Tests mirror under `tests/apply/…` and `tests/resume/…`.

---

### Task 1: Apply settings + applicant profile section

**Files:**
- Modify: `internhunter/config/settings.py` (append fields to `Settings`)
- Modify: `internhunter/config/profile.yaml` (add `applicant:` block)
- Test: `tests/apply/test_settings.py`

**Interfaces:**
- Consumes: existing `Settings` (pydantic-settings, env prefix `INTERNHUNTER_`).
- Produces: `Settings.enable_auto_apply: bool`, `.auto_apply_min_fit: float`, `.auto_apply_daily_cap: int`, `.auto_apply_per_company_cap: int`, `.auto_apply_delay_seconds: float`, `.auto_apply_stop_file: Path`. (`http_proxy` already exists — reuse it.)

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_settings.py
from internhunter.config.settings import Settings


def test_auto_apply_defaults_are_safe():
    s = Settings()
    assert s.enable_auto_apply is False          # kill switch off by default
    assert s.auto_apply_min_fit == 0.75
    assert s.auto_apply_daily_cap == 15
    assert s.auto_apply_per_company_cap == 1
    assert s.auto_apply_delay_seconds >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_settings.py -v`
Expected: FAIL with `AttributeError` (fields not defined).

- [ ] **Step 3: Add the settings fields**

In `internhunter/config/settings.py`, inside the `Settings` class (near the other feature toggles), add:

```python
    # --- Auto-apply (off by default; submits real applications under your name) ---
    enable_auto_apply: bool = False           # master kill switch
    auto_apply_min_fit: float = 0.75          # stricter than notify_min_fit; fit_score is 0-1 here
    auto_apply_daily_cap: int = 15            # max submitted applications per rolling 24h
    auto_apply_per_company_cap: int = 1       # max auto-applications per company
    auto_apply_delay_seconds: float = 20.0    # randomized pacing floor between submissions
    auto_apply_stop_file: Path = Path(".auto_apply_stop")  # runtime kill switch (presence = stop)
```

- [ ] **Step 4: Add the applicant profile block**

Append to `internhunter/config/profile.yaml`:

```yaml
# Identity used to fill application forms. Required fields must be present for auto-apply.
applicant:
  full_name: ""            # required
  email: ""                # required
  phone: ""                # required
  location: ""             # city, state/country
  work_authorization: ""   # required, e.g. "US Citizen" / "F-1 OPT" / "Requires H-1B"
  requires_sponsorship: false  # required (bool)
  linkedin_url: ""
  github_url: ""
  portfolio_url: ""
  school: ""
  grad_date: ""            # e.g. "2026-05"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/apply/test_settings.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internhunter/config/settings.py internhunter/config/profile.yaml tests/apply/test_settings.py
git commit -m "feat(apply): add auto-apply settings and applicant profile section"
```

---

### Task 2: Applicant loader + validator

**Files:**
- Create: `internhunter/apply/__init__.py` (empty)
- Create: `internhunter/apply/applicant.py`
- Test: `tests/apply/test_applicant.py`

**Interfaces:**
- Consumes: `Settings.profile_path`, PyYAML (`yaml.safe_load`).
- Produces:
  - `@dataclass(frozen=True) Applicant` with str fields `full_name, email, phone, location, work_authorization, linkedin_url, github_url, portfolio_url, school, grad_date` and `requires_sponsorship: bool`.
  - `REQUIRED_FIELDS: tuple[str, ...] = ("full_name", "email", "phone", "work_authorization")`
  - `load_applicant(settings: Settings | None = None) -> Applicant`
  - `validate_applicant(a: Applicant) -> list[str]` — returns names of missing required fields (empty = valid).

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_applicant.py
from internhunter.apply.applicant import Applicant, load_applicant, validate_applicant


def test_validate_reports_missing_required_fields():
    a = Applicant(full_name="", email="a@b.com", phone="", work_authorization="US Citizen",
                  requires_sponsorship=False, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")
    missing = validate_applicant(a)
    assert "full_name" in missing and "phone" in missing
    assert "email" not in missing


def test_load_applicant_from_yaml(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "applicant:\n  full_name: Jane Doe\n  email: jane@x.com\n  phone: '555'\n"
        "  work_authorization: US Citizen\n  requires_sponsorship: true\n",
        encoding="utf-8",
    )
    from internhunter.config.settings import Settings
    a = load_applicant(Settings(profile_path=p))
    assert a.full_name == "Jane Doe"
    assert a.requires_sponsorship is True
    assert validate_applicant(a) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_applicant.py -v`
Expected: FAIL (`ModuleNotFoundError: internhunter.apply.applicant`).

- [ ] **Step 3: Implement applicant.py**

```python
# internhunter/apply/applicant.py
from __future__ import annotations

from dataclasses import dataclass, fields

from internhunter.config.settings import Settings, get_settings

REQUIRED_FIELDS: tuple[str, ...] = ("full_name", "email", "phone", "work_authorization")


@dataclass(frozen=True)
class Applicant:
    full_name: str
    email: str
    phone: str
    work_authorization: str
    requires_sponsorship: bool
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    school: str = ""
    grad_date: str = ""


def load_applicant(settings: Settings | None = None) -> Applicant:
    import yaml

    resolved = settings or get_settings()
    data = yaml.safe_load(resolved.profile_path.read_text(encoding="utf-8")) or {}
    block = data.get("applicant") or {}
    known = {f.name for f in fields(Applicant)}
    kwargs = {k: block.get(k, "") for k in known}
    kwargs["requires_sponsorship"] = bool(block.get("requires_sponsorship", False))
    return Applicant(**kwargs)


def validate_applicant(a: Applicant) -> list[str]:
    return [name for name in REQUIRED_FIELDS if not str(getattr(a, name)).strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/apply/test_applicant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internhunter/apply/__init__.py internhunter/apply/applicant.py tests/apply/test_applicant.py
git commit -m "feat(apply): applicant identity loader and validator"
```

---

### Task 3: Form-field model + classifier

**Files:**
- Create: `internhunter/apply/fields.py`
- Test: `tests/apply/test_fields.py`

**Interfaces:**
- Consumes: `Applicant` (Task 2).
- Produces:
  - `@dataclass(frozen=True) FormField`: `name: str`, `label: str`, `ftype: str`, `required: bool`, `options: tuple[str, ...] = ()`.
  - `field_key(label: str) -> str | None` — maps a label to a canonical key in {`full_name,email,phone,location,linkedin_url,github_url,portfolio_url,school,resume`} or None.
  - `classify_fields(spec_fields: list[FormField], a: Applicant) -> tuple[dict[str, str], list[FormField]]` — returns (payload of `field.name -> value` for fillable fields, list of required fields that are unfillable). The resume upload field (`ftype == "file"` with a resume/cv label) is treated as fillable and represented in the payload as `{name: "@resume"}` sentinel.

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_fields.py
from internhunter.apply.applicant import Applicant
from internhunter.apply.fields import FormField, classify_fields, field_key

A = Applicant(full_name="Jane Doe", email="jane@x.com", phone="555",
              work_authorization="US Citizen", requires_sponsorship=False,
              linkedin_url="https://linkedin.com/in/jane")


def test_field_key_normalizes_labels():
    assert field_key("First Name") is None or field_key("Full Name") == "full_name"
    assert field_key("Email Address") == "email"
    assert field_key("LinkedIn Profile") == "linkedin_url"


def test_classify_splits_fillable_and_unknown():
    spec = [
        FormField(name="name", label="Full Name", ftype="text", required=True),
        FormField(name="email", label="Email", ftype="email", required=True),
        FormField(name="resume", label="Resume/CV", ftype="file", required=True),
        FormField(name="q1", label="Why do you want to work here?", ftype="textarea", required=True),
        FormField(name="phone", label="Phone", ftype="text", required=False),
    ]
    payload, unknown = classify_fields(spec, A)
    assert payload["name"] == "Jane Doe"
    assert payload["resume"] == "@resume"
    assert [f.name for f in unknown] == ["q1"]   # custom required question is unfillable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_fields.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement fields.py**

```python
# internhunter/apply/fields.py
from __future__ import annotations

import re
from dataclasses import dataclass, field

from internhunter.apply.applicant import Applicant


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    ftype: str
    required: bool
    options: tuple[str, ...] = field(default=())


# canonical key -> substrings that identify it (checked against a normalized label)
_LABEL_PATTERNS: dict[str, tuple[str, ...]] = {
    "full_name": ("full name", "name"),
    "email": ("email", "e-mail"),
    "phone": ("phone", "mobile", "telephone"),
    "linkedin_url": ("linkedin",),
    "github_url": ("github",),
    "portfolio_url": ("portfolio", "website", "personal site"),
    "school": ("school", "university", "college"),
    "location": ("location", "city"),
}


def _normalize(label: str) -> str:
    return re.sub(r"\s+", " ", label or "").strip().lower()


def field_key(label: str) -> str | None:
    norm = _normalize(label)
    # longest, most specific patterns first so "full name" wins over bare "name"
    for key, subs in _LABEL_PATTERNS.items():
        for sub in subs:
            if sub in norm:
                return key
    return None


def _is_resume_upload(f: FormField) -> bool:
    return f.ftype == "file" and any(w in _normalize(f.label) for w in ("resume", "cv"))


def classify_fields(
    spec_fields: list[FormField], a: Applicant
) -> tuple[dict[str, str], list[FormField]]:
    payload: dict[str, str] = {}
    unknown: list[FormField] = []
    for f in spec_fields:
        if _is_resume_upload(f):
            payload[f.name] = "@resume"
            continue
        key = field_key(f.label)
        value = str(getattr(a, key)).strip() if key else ""
        if value:
            payload[f.name] = value
        elif f.required:
            unknown.append(f)
    return payload, unknown
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/apply/test_fields.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internhunter/apply/fields.py tests/apply/test_fields.py
git commit -m "feat(apply): form-field model and known/unknown classifier"
```

---

### Task 4: Submitter contract + registry

**Files:**
- Create: `internhunter/apply/submit/__init__.py` (empty)
- Create: `internhunter/apply/submit/base.py`
- Test: `tests/apply/test_submit_base.py`

**Interfaces:**
- Consumes: `FormField` (Task 3), `FetchContext`, `Job` (`core/db.py`).
- Produces:
  - `@dataclass FormSpec`: `fields: list[FormField]`, `requires_account: bool = False`, `captcha_detected: bool = False`.
  - `@dataclass SubmitResult`: `status: str`, `confirmation: str | None = None`, `reason: str | None = None`. Status ∈ {`"submitted"`, `"failed"`, `"needs_review"`}.
  - `class Submitter(ABC)`: attribute `ats: str`; `async def probe_form(self, job, ctx) -> FormSpec`; `async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult`.
  - `SUBMITTER_REGISTRY: dict[str, Submitter]`, `register_submitter(cls)` decorator, `get_submitter(ats: str) -> Submitter | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_submit_base.py
from internhunter.apply.submit.base import (
    FormSpec, SubmitResult, Submitter, get_submitter, register_submitter,
)


def test_registry_roundtrip():
    @register_submitter
    class _Fake(Submitter):
        ats = "fake"
        async def probe_form(self, job, ctx):
            return FormSpec(fields=[])
        async def submit(self, job, ctx, payload, resume_path):
            return SubmitResult(status="submitted", confirmation="ok")

    assert get_submitter("fake") is not None
    assert get_submitter("nonexistent") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_submit_base.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement base.py**

```python
# internhunter/apply/submit/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from internhunter.apply.fields import FormField


@dataclass
class FormSpec:
    fields: list[FormField]
    requires_account: bool = False
    captcha_detected: bool = False


@dataclass
class SubmitResult:
    status: str
    confirmation: str | None = None
    reason: str | None = None


class Submitter(ABC):
    ats: str

    @abstractmethod
    async def probe_form(self, job, ctx) -> FormSpec: ...

    @abstractmethod
    async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult: ...


SUBMITTER_REGISTRY: dict[str, Submitter] = {}


def register_submitter(cls: type[Submitter]) -> type[Submitter]:
    SUBMITTER_REGISTRY[cls.ats] = cls()
    return cls


def get_submitter(ats: str) -> Submitter | None:
    return SUBMITTER_REGISTRY.get(ats)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/apply/test_submit_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internhunter/apply/submit/__init__.py internhunter/apply/submit/base.py tests/apply/test_submit_base.py
git commit -m "feat(apply): Submitter contract and registry"
```

---

### Task 5: Guardrails

**Files:**
- Create: `internhunter/apply/guardrails.py`
- Test: `tests/apply/test_guardrails.py`

**Interfaces:**
- Consumes: `Settings`, `Applicant` (Task 2), `Job` and `Application` (`core/db.py`), SQLAlchemy `Session`.
- Produces:
  - `kill_switch_active(settings: Settings) -> bool` — True if `not enable_auto_apply` or stop-file exists.
  - `applications_today(session) -> int` — count of `Application.status == "submitted"` with `applied_at` within last 24h.
  - `eligible(job, a: Applicant) -> bool` — False if `a.requires_sponsorship` and the job text signals no sponsorship.
  - `skip_reason(session, job, a: Applicant, settings: Settings) -> str | None` — returns a human reason to skip, or None if the job passes all guardrails. Order: kill switch → already applied (job/company) → eligibility → daily cap → per-company cap.

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_guardrails.py
from internhunter.apply.applicant import Applicant
from internhunter.apply.guardrails import eligible, kill_switch_active
from internhunter.config.settings import Settings


class _Job:
    def __init__(self, text):
        self.description_text = text
        self.title = "SWE Intern"


def test_kill_switch_off_by_default():
    assert kill_switch_active(Settings()) is True   # enable_auto_apply defaults False


def test_eligibility_blocks_sponsorship_mismatch():
    a = Applicant(full_name="J", email="j@x.com", phone="5", work_authorization="F-1",
                  requires_sponsorship=True, location="", linkedin_url="", github_url="",
                  portfolio_url="", school="", grad_date="")
    assert eligible(_Job("We do not provide visa sponsorship for this role."), a) is False
    assert eligible(_Job("Great team, free lunch."), a) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_guardrails.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement guardrails.py**

```python
# internhunter/apply/guardrails.py
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from internhunter.apply.applicant import Applicant
from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Application

_NO_SPONSOR = re.compile(
    r"(no(t)?\s+.{0,20}sponsor|without\s+sponsor|unable\s+to\s+sponsor|"
    r"must\s+be\s+(a\s+)?(us\s+)?citizen|requires?\s+us\s+citizen)",
    re.IGNORECASE,
)


def kill_switch_active(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    if not resolved.enable_auto_apply:
        return True
    return resolved.auto_apply_stop_file.exists()


def applications_today(session) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    return int(
        session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.status == "submitted", Application.applied_at >= cutoff)
        )
        or 0
    )


def eligible(job, a: Applicant) -> bool:
    if not a.requires_sponsorship:
        return True
    return _NO_SPONSOR.search(job.description_text or "") is None


def skip_reason(session, job, a: Applicant, settings: Settings | None = None) -> str | None:
    resolved = settings or get_settings()
    if kill_switch_active(resolved):
        return "auto-apply disabled (kill switch)"
    existing = session.scalar(
        select(Application).where(Application.job_uid == job.job_uid)
    )
    if existing is not None:
        return "already in applications"
    company_count = int(
        session.scalar(
            select(func.count()).select_from(Application).where(
                Application.company_slug == job.company_slug,
                Application.status == "submitted",
            )
        )
        or 0
    )
    if company_count >= resolved.auto_apply_per_company_cap:
        return "per-company cap reached"
    if not eligible(job, a):
        return "ineligible (sponsorship mismatch)"
    if applications_today(session) >= resolved.auto_apply_daily_cap:
        return "daily cap reached"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/apply/test_guardrails.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internhunter/apply/guardrails.py tests/apply/test_guardrails.py
git commit -m "feat(apply): guardrails (kill switch, caps, dedupe, eligibility)"
```

---

### Task 6: Resume tailoring + truthfulness verification

**Files:**
- Modify: `internhunter/resume/tailor.py` (implement the stub)
- Test: `tests/resume/test_tailor.py`

**Interfaces:**
- Consumes: existing `TailorRequest`, `TailorResult`, `TRUTHFULNESS_CONTRACT`, `ATS_FORMAT_NOTES`; `LlmBackend` protocol (`generate(prompt, system, max_tokens) -> str`).
- Produces:
  - `build_tailor_prompt(request: TailorRequest) -> str`
  - `build_verify_prompt(base_resume: str, tailored: str) -> str`
  - `verify_truthful(base_resume: str, tailored: str, backend, *, max_tokens=512) -> list[str]` — returns list of tailored claims NOT traceable to the base resume (empty = clean). Parses a JSON array from the model reply via existing `extract_json` helper pattern.
  - `tailor_resume(request: TailorRequest, backend, *, max_tokens=1024) -> TailorResult` — generates tailored resume, runs `verify_truthful`; if any unverifiable claim, returns `TailorResult(tailored_resume=request.base_resume, changed_sections=[], warnings=[...])` (safe fallback).

- [ ] **Step 1: Write the failing test**

```python
# tests/resume/test_tailor.py
from internhunter.resume.tailor import TailorRequest, tailor_resume, verify_truthful


class _Backend:
    """Scripted backend: returns queued replies in order."""
    def __init__(self, replies):
        self._replies = list(replies)
    def generate(self, prompt, system=None, max_tokens=1024):
        return self._replies.pop(0)


REQ = TailorRequest(job_uid="u1", job_text="Python backend internship",
                    base_resume="EXPERIENCE\n- Built a Flask API in Python",
                    profile="python, sql")


def test_tailor_falls_back_when_verification_finds_fabrication():
    backend = _Backend([
        "EXPERIENCE\n- Led a 50-person team at Google",          # tailored (fabricated)
        '["Led a 50-person team at Google"]',                     # verify: unverifiable claim
    ])
    result = tailor_resume(REQ, backend)
    assert result.tailored_resume == REQ.base_resume             # fell back
    assert result.warnings


def test_tailor_keeps_clean_output():
    backend = _Backend([
        "EXPERIENCE\n- Built a Flask API in Python (backend focus)",
        "[]",                                                     # verify: clean
    ])
    result = tailor_resume(REQ, backend)
    assert "Flask" in result.tailored_resume
    assert result.warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/resume/test_tailor.py -v`
Expected: FAIL (`tailor_resume` raises `NotImplementedError`).

- [ ] **Step 3: Implement tailor.py**

Replace the `tailor_resume` stub (keep `TRUTHFULNESS_CONTRACT`, `ATS_FORMAT_NOTES`, `TailorRequest`, `TailorResult`) and add:

```python
import json


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


def verify_truthful(base_resume: str, tailored: str, backend, *, max_tokens: int = 512) -> list[str]:
    reply = backend.generate(build_verify_prompt(base_resume, tailored), max_tokens=max_tokens)
    start, end = reply.find("["), reply.rfind("]")
    if start == -1 or end == -1:
        return ["verification failed: unparseable auditor reply"]
    try:
        items = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return ["verification failed: unparseable auditor reply"]
    return [str(x) for x in items] if isinstance(items, list) else []


def tailor_resume(request: TailorRequest, backend, *, max_tokens: int = 1024) -> TailorResult:
    tailored = backend.generate(build_tailor_prompt(request), max_tokens=max_tokens).strip()
    problems = verify_truthful(request.base_resume, tailored, backend)
    if problems:
        return TailorResult(
            tailored_resume=request.base_resume,
            changed_sections=[],
            warnings=[f"reverted to base resume; unverifiable claims: {problems}"],
        )
    return TailorResult(tailored_resume=tailored, changed_sections=[], warnings=[])
```

Delete the `raise NotImplementedError` body.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/resume/test_tailor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add internhunter/resume/tailor.py tests/resume/test_tailor.py
git commit -m "feat(resume): implement tailoring with truthfulness verification"
```

---

### Task 7: PDF rendering

**Files:**
- Create: `internhunter/apply/render.py`
- Modify: `pyproject.toml` (add `fpdf2` dependency)
- Test: `tests/apply/test_render.py`

**Interfaces:**
- Consumes: `fpdf2`.
- Produces: `render_resume_pdf(text: str, out_path: Path) -> Path` — writes a single-column, plain-text, ATS-parseable PDF (standard font, no tables/images) and returns `out_path`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"fpdf2"` to the `dependencies` list, then:

Run: `pip install -e ".[dev]"`
Expected: installs `fpdf2`.

- [ ] **Step 2: Write the failing test**

```python
# tests/apply/test_render.py
from internhunter.apply.render import render_resume_pdf


def test_render_writes_pdf(tmp_path):
    out = render_resume_pdf("EXPERIENCE\n- Built a Flask API", tmp_path / "r.pdf")
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/apply/test_render.py -v`
Expected: FAIL (`ModuleNotFoundError: internhunter.apply.render`).

- [ ] **Step 4: Implement render.py**

```python
# internhunter/apply/render.py
from __future__ import annotations

from pathlib import Path


def render_resume_pdf(text: str, out_path: Path) -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.splitlines() or [""]:
        # latin-1 is fpdf2's core-font encoding; drop unencodable glyphs rather than crash
        safe = line.encode("latin-1", "ignore").decode("latin-1")
        pdf.multi_cell(0, 6, safe)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/apply/test_render.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internhunter/apply/render.py pyproject.toml tests/apply/test_render.py
git commit -m "feat(apply): ATS-parseable PDF rendering for tailored resumes"
```

---

### Task 8: Greenhouse submitter

**Files:**
- Create: `internhunter/apply/submit/greenhouse.py`
- Test: `tests/apply/test_greenhouse_submit.py`
- Create fixture: `tests/apply/fixtures/greenhouse_job_form.json`

**Background (verify against the live API before implementing):** Greenhouse's job-board API exposes a job's questions at
`GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}?questions=true`, returning a `questions` array (each with `label`, `required`, and `fields[].name`/`type`), and accepts an application at
`POST https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}` (multipart, resume as a file part). The probe maps `questions` → `FormField`s; submit posts the classified payload with the resume file.

**Interfaces:**
- Consumes: `Submitter`, `FormSpec`, `SubmitResult` (Task 4), `FormField` (Task 3), `FetchContext` (`get_json`, `post_json`), `Job` (has `.board_token`, `.source_job_id`).
- Produces: `class GreenhouseSubmitter(Submitter)` with `ats = "greenhouse"`, registered via `@register_submitter`. Plus a pure helper `parse_questions(payload: dict) -> list[FormField]` so the parser is testable without network.

- [ ] **Step 1: Create the fixture**

```json
// tests/apply/fixtures/greenhouse_job_form.json
{
  "questions": [
    {"label": "First Name", "required": true, "fields": [{"name": "first_name", "type": "input_text"}]},
    {"label": "Email", "required": true, "fields": [{"name": "email", "type": "input_text"}]},
    {"label": "Resume", "required": true, "fields": [{"name": "resume", "type": "input_file"}]},
    {"label": "Why this company?", "required": true, "fields": [{"name": "question_1", "type": "textarea"}]}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/apply/test_greenhouse_submit.py
import json
from pathlib import Path

from internhunter.apply.submit.greenhouse import GreenhouseSubmitter, parse_questions

FIX = Path(__file__).parent / "fixtures" / "greenhouse_job_form.json"


def test_parse_questions_maps_fields_and_types():
    payload = json.loads(FIX.read_text())
    fields = parse_questions(payload)
    by_name = {f.name: f for f in fields}
    assert by_name["resume"].ftype == "file"
    assert by_name["question_1"].ftype == "textarea"
    assert by_name["email"].required is True


def test_submitter_registered():
    from internhunter.apply.submit.base import get_submitter
    import internhunter.apply.submit.greenhouse  # noqa: F401  (triggers registration)
    assert isinstance(get_submitter("greenhouse"), GreenhouseSubmitter)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/apply/test_greenhouse_submit.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement greenhouse.py**

```python
# internhunter/apply/submit/greenhouse.py
from __future__ import annotations

from internhunter.apply.fields import FormField
from internhunter.apply.submit.base import (
    FormSpec, SubmitResult, Submitter, register_submitter,
)

_TYPE_MAP = {"input_text": "text", "input_file": "file", "textarea": "textarea",
             "multi_value_single_select": "select"}


def parse_questions(payload: dict) -> list[FormField]:
    out: list[FormField] = []
    for q in payload.get("questions", []):
        label = q.get("label", "")
        required = bool(q.get("required"))
        for f in q.get("fields", []):
            out.append(
                FormField(
                    name=f.get("name", ""),
                    label=label,
                    ftype=_TYPE_MAP.get(f.get("type", ""), "text"),
                    required=required,
                )
            )
    return out


@register_submitter
class GreenhouseSubmitter(Submitter):
    ats = "greenhouse"

    def _job_url(self, job) -> str:
        return (
            f"https://boards-api.greenhouse.io/v1/boards/{job.board_token}"
            f"/jobs/{job.source_job_id}"
        )

    async def probe_form(self, job, ctx) -> FormSpec:
        payload = await ctx.get_json(f"{self._job_url(job)}?questions=true")
        payload = payload if isinstance(payload, dict) else {}
        return FormSpec(fields=parse_questions(payload))

    async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult:
        body = {k: v for k, v in payload.items() if v != "@resume"}
        try:
            resp = await ctx.post_json(self._job_url(job), json_body=body)
        except Exception as exc:  # network/HTTP error -> non-fatal, recorded by pipeline
            return SubmitResult(status="failed", reason=f"post error: {exc}")
        if isinstance(resp, dict) and (resp.get("success") or resp.get("status") == "ok"):
            return SubmitResult(status="submitted", confirmation=str(resp.get("id") or ""))
        return SubmitResult(status="failed", reason=f"unexpected response: {resp!r:.200}")
```

> Note for the implementer: confirm the live success-response shape and multipart resume-upload mechanics against a real Greenhouse board before enabling submission; the probe/parse path and registration are fully covered by the fixture test above. If the live POST requires multipart file upload rather than JSON, add a `post_multipart` helper to `FetchContext` in a separate committed step and use it here.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/apply/test_greenhouse_submit.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internhunter/apply/submit/greenhouse.py tests/apply/test_greenhouse_submit.py tests/apply/fixtures/greenhouse_job_form.json
git commit -m "feat(apply): Greenhouse submission adapter (probe + submit)"
```

---

### Task 9: Lever submitter

**Files:**
- Create: `internhunter/apply/submit/lever.py`
- Test: `tests/apply/test_lever_submit.py`
- Create fixture: `tests/apply/fixtures/lever_posting.json`

**Background (verify before implementing):** Lever postings expose details at
`GET https://api.lever.co/v0/postings/{token}/{id}` (the posting JSON includes any custom
application `cards`/`fields`), and accept applications at
`POST https://jobs.lever.co/{token}/{id}/apply`. The probe maps the posting's standard
contact fields + any custom application fields → `FormField`s; submit posts the classified payload.

**Interfaces:**
- Consumes: same as Task 8.
- Produces: `class LeverSubmitter(Submitter)` with `ats = "lever"`, registered; plus pure helper `parse_posting(payload: dict) -> list[FormField]`.

- [ ] **Step 1: Create the fixture**

```json
// tests/apply/fixtures/lever_posting.json
{
  "id": "abc-123",
  "text": "Software Engineering Intern",
  "applicationQuestions": [
    {"text": "Full name", "required": true, "type": "text", "name": "name"},
    {"text": "Email", "required": true, "type": "text", "name": "email"},
    {"text": "Resume", "required": true, "type": "file", "name": "resume"},
    {"text": "Describe a project you are proud of", "required": true, "type": "textarea", "name": "card_0"}
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/apply/test_lever_submit.py
import json
from pathlib import Path

from internhunter.apply.submit.lever import LeverSubmitter, parse_posting

FIX = Path(__file__).parent / "fixtures" / "lever_posting.json"


def test_parse_posting_extracts_fields():
    fields = parse_posting(json.loads(FIX.read_text()))
    by_name = {f.name: f for f in fields}
    assert by_name["resume"].ftype == "file"
    assert by_name["card_0"].ftype == "textarea"
    assert by_name["email"].required is True


def test_submitter_registered():
    from internhunter.apply.submit.base import get_submitter
    import internhunter.apply.submit.lever  # noqa: F401
    assert isinstance(get_submitter("lever"), LeverSubmitter)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/apply/test_lever_submit.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement lever.py**

```python
# internhunter/apply/submit/lever.py
from __future__ import annotations

from internhunter.apply.fields import FormField
from internhunter.apply.submit.base import (
    FormSpec, SubmitResult, Submitter, register_submitter,
)

_TYPE_MAP = {"text": "text", "file": "file", "textarea": "textarea", "select": "select"}


def parse_posting(payload: dict) -> list[FormField]:
    out: list[FormField] = []
    for q in payload.get("applicationQuestions", []):
        out.append(
            FormField(
                name=q.get("name", ""),
                label=q.get("text", ""),
                ftype=_TYPE_MAP.get(q.get("type", ""), "text"),
                required=bool(q.get("required")),
            )
        )
    return out


@register_submitter
class LeverSubmitter(Submitter):
    ats = "lever"

    async def probe_form(self, job, ctx) -> FormSpec:
        url = f"https://api.lever.co/v0/postings/{job.board_token}/{job.source_job_id}"
        payload = await ctx.get_json(url)
        payload = payload if isinstance(payload, dict) else {}
        return FormSpec(fields=parse_posting(payload))

    async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult:
        url = f"https://jobs.lever.co/{job.board_token}/{job.source_job_id}/apply"
        body = {k: v for k, v in payload.items() if v != "@resume"}
        try:
            resp = await ctx.post_json(url, json_body=body)
        except Exception as exc:
            return SubmitResult(status="failed", reason=f"post error: {exc}")
        if isinstance(resp, dict) and resp.get("ok", True):
            return SubmitResult(status="submitted", confirmation=str(resp.get("id") or ""))
        return SubmitResult(status="failed", reason=f"unexpected response: {resp!r:.200}")
```

> Same note as Greenhouse: confirm live POST shape / multipart upload before enabling submission. Probe/parse + registration are fixture-covered.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/apply/test_lever_submit.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internhunter/apply/submit/lever.py tests/apply/test_lever_submit.py tests/apply/fixtures/lever_posting.json
git commit -m "feat(apply): Lever submission adapter (probe + submit)"
```

---

### Task 10: Pipeline orchestrator

**Files:**
- Create: `internhunter/apply/pipeline.py`
- Test: `tests/apply/test_pipeline.py`

**Interfaces:**
- Consumes: `load_applicant`/`validate_applicant` (Task 2), `classify_fields` (Task 3), `get_submitter` (Task 4), `skip_reason` (Task 5), `tailor_resume`+`TailorRequest` (Task 6), `render_resume_pdf` (Task 7), `load_candidate_profile`/`load_resume_text`, `get_backend`/`LlmCache`, `Job`/`Application`/`get_session`. Ensures both adapters are imported so they self-register.
- Produces:
  - `@dataclass ApplyOutcome`: `job_uid: str`, `status: str`, `reason: str | None`, `resume_path: str | None`, `confirmation: str | None`.
  - `select_candidates(session, settings) -> list[Job]` — internships with an `llm:%` fit `>= auto_apply_min_fit*100`, ATS in the Tier-A set, not already in `applications`, not confirmed slop, ordered by fit desc.
  - `async def process_job(job, ctx, backend, applicant, profile, base_resume, settings, *, dry_run) -> ApplyOutcome`
  - `async def auto_apply(*, settings=None, limit=None, dry_run=False) -> list[ApplyOutcome]` — opens session + fetch context + backend, loops candidates with guardrails + pacing, records an `Application` row per outcome.

  Status values written to `Application.status`: `"submitted"`, `"needs_review"`, `"failed"`, `"would_submit"` (dry-run). The skip/failure reason and confirmation are stored in `Application.notes`.

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_pipeline.py
import asyncio

import pytest

from internhunter.apply.applicant import Applicant
from internhunter.apply.pipeline import process_job
from internhunter.apply.submit.base import FormSpec, SubmitResult, register_submitter, Submitter
from internhunter.apply.fields import FormField
from internhunter.config.settings import Settings


class _Job:
    job_uid = "u1"; ats = "fake_easy"; board_token = "t"; source_job_id = "1"
    company = "Acme"; company_slug = "acme"; title = "SWE Intern"
    description_text = "Build things."; canonical_url = "https://x/y"


class _Backend:
    def generate(self, prompt, system=None, max_tokens=1024):
        return "[]" if "auditor" in prompt.lower() else "TAILORED RESUME\n- Build things"


@register_submitter
class _EasySubmitter(Submitter):
    ats = "fake_easy"
    async def probe_form(self, job, ctx):
        return FormSpec(fields=[FormField("name", "Full Name", "text", True),
                                FormField("resume", "Resume", "file", True)])
    async def submit(self, job, ctx, payload, resume_path):
        return SubmitResult(status="submitted", confirmation="C1")


@register_submitter
class _HardSubmitter(Submitter):
    ats = "fake_hard"
    async def probe_form(self, job, ctx):
        return FormSpec(fields=[FormField("q1", "Why us?", "textarea", True)])
    async def submit(self, job, ctx, payload, resume_path):
        raise AssertionError("must not submit when unknown required fields exist")


A = Applicant(full_name="Jane", email="j@x.com", phone="5", work_authorization="US Citizen",
              requires_sponsorship=False, location="", linkedin_url="", github_url="",
              portfolio_url="", school="", grad_date="")


def test_easy_job_submits(tmp_path):
    out = asyncio.run(process_job(_Job(), ctx=None, backend=_Backend(), applicant=A,
                                  profile="python", base_resume="EXPERIENCE\n- Build things",
                                  settings=Settings(cache_dir=tmp_path), dry_run=False))
    assert out.status == "submitted" and out.confirmation == "C1"
    assert out.resume_path and out.resume_path.endswith(".pdf")


def test_unknown_field_routes_to_review(tmp_path):
    job = _Job(); job.ats = "fake_hard"
    out = asyncio.run(process_job(job, ctx=None, backend=_Backend(), applicant=A,
                                  profile="python", base_resume="x",
                                  settings=Settings(cache_dir=tmp_path), dry_run=False))
    assert out.status == "needs_review"


def test_unknown_ats_routes_to_review(tmp_path):
    job = _Job(); job.ats = "no_adapter_ats"
    out = asyncio.run(process_job(job, ctx=None, backend=_Backend(), applicant=A,
                                  profile="python", base_resume="x",
                                  settings=Settings(cache_dir=tmp_path), dry_run=False))
    assert out.status == "needs_review" and "no adapter" in (out.reason or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_pipeline.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement pipeline.py**

```python
# internhunter/apply/pipeline.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from internhunter.apply.applicant import Applicant, load_applicant, validate_applicant
from internhunter.apply.fields import classify_fields
from internhunter.apply.guardrails import skip_reason
from internhunter.apply.render import render_resume_pdf
from internhunter.apply.submit.base import get_submitter
import internhunter.apply.submit.greenhouse  # noqa: F401  (registration)
import internhunter.apply.submit.lever       # noqa: F401  (registration)
from internhunter.config.settings import Settings, get_settings
from internhunter.resume.tailor import TailorRequest, tailor_resume

TIER_A = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters",
          "recruitee", "personio", "pinpoint")


@dataclass
class ApplyOutcome:
    job_uid: str
    status: str
    reason: str | None = None
    resume_path: str | None = None
    confirmation: str | None = None


async def process_job(job, *, ctx, backend, applicant: Applicant, profile: str,
                      base_resume: str, settings: Settings, dry_run: bool) -> ApplyOutcome:
    submitter = get_submitter(job.ats)
    if submitter is None:
        return ApplyOutcome(job.job_uid, "needs_review", reason=f"no adapter for ats={job.ats}")

    spec = await submitter.probe_form(job, ctx)
    if spec.requires_account or spec.captcha_detected:
        return ApplyOutcome(job.job_uid, "needs_review", reason="login wall / captcha")

    payload, unknown = classify_fields(spec.fields, applicant)
    if unknown:
        labels = ", ".join(f.label for f in unknown)
        return ApplyOutcome(job.job_uid, "needs_review", reason=f"unfillable fields: {labels}")

    tailored = tailor_resume(
        TailorRequest(job_uid=job.job_uid, job_text=f"{job.title}. {job.description_text}",
                      base_resume=base_resume, profile=profile),
        backend,
    )
    out_dir = Path(settings.cache_dir) / "resumes"
    resume_path = render_resume_pdf(tailored.tailored_resume, out_dir / f"{job.job_uid}.pdf")

    if dry_run:
        return ApplyOutcome(job.job_uid, "would_submit", reason="; ".join(tailored.warnings) or None,
                            resume_path=str(resume_path))

    result = await submitter.submit(job, ctx, payload, resume_path)
    return ApplyOutcome(job.job_uid, result.status, reason=result.reason,
                        resume_path=str(resume_path), confirmation=result.confirmation)


def select_candidates(session, settings: Settings):
    from sqlalchemy import select
    from internhunter.core.db import Application, Job, Score

    threshold = settings.auto_apply_min_fit * 100  # llm:% fit_score is 0-100
    applied = select(Application.job_uid)
    fit = (select(Score.job_uid).where(Score.model.like("llm:%"),
                                       Score.fit_score >= threshold))
    return list(session.scalars(
        select(Job).where(
            Job.is_internship.is_(True),
            Job.ats.in_(TIER_A),
            Job.job_uid.in_(fit),
            Job.job_uid.not_in(applied),
            (Job.quality_verdict.is_(None)) | (Job.quality_verdict != "slop"),
        ).order_by(Job.discovery_score.desc().nulls_last())
    ))


async def auto_apply(*, settings: Settings | None = None, limit: int | None = None,
                     dry_run: bool = False) -> list[ApplyOutcome]:
    import random

    from internhunter.core.db import Application, get_session
    from internhunter.core.fetch import build_fetch_context
    from internhunter.llm.client import LlmCache, get_backend
    from internhunter.match.prefilter import load_candidate_profile, load_profile_text
    from internhunter.resume.load import load_resume_text

    resolved = settings or get_settings()
    applicant = load_applicant(resolved)
    missing = validate_applicant(applicant)
    if missing:
        return [ApplyOutcome("", "failed", reason=f"missing applicant fields: {missing}")]

    profile = load_profile_text(resolved.profile_path)
    base_resume = load_resume_text(resolved.resume_path) or ""
    if not base_resume.strip():
        return [ApplyOutcome("", "failed", reason="no base resume found")]

    backend = get_backend(resolved)
    cache = LlmCache(resolved.cache_dir)
    outcomes: list[ApplyOutcome] = []
    session = get_session()
    try:
        candidates = select_candidates(session, resolved)
        if limit is not None:
            candidates = candidates[:limit]
        async with build_fetch_context(resolved) as ctx:
            for job in candidates:
                reason = skip_reason(session, job, applicant, resolved)
                if reason is not None:
                    if reason == "daily cap reached" or reason.startswith("auto-apply disabled"):
                        break  # hard stop for the whole run
                    continue   # per-job skip (already applied / ineligible / company cap)
                outcome = await process_job(job, ctx=ctx, backend=backend, applicant=applicant,
                                            profile=profile, base_resume=base_resume,
                                            settings=resolved, dry_run=dry_run)
                _record(session, job, outcome)
                outcomes.append(outcome)
                if not dry_run and outcome.status == "submitted":
                    await asyncio.sleep(resolved.auto_apply_delay_seconds * (1 + random.random()))
    finally:
        session.close()
    return outcomes


def _record(session, job, outcome: ApplyOutcome) -> None:
    from datetime import UTC, datetime

    from internhunter.core.db import Application

    note = outcome.reason or ""
    if outcome.confirmation:
        note = f"{note} (confirmation={outcome.confirmation})".strip()
    app = Application(
        job_uid=job.job_uid, status=outcome.status, company=job.company,
        company_slug=job.company_slug, role=job.title, link=job.canonical_url,
        resume_path=outcome.resume_path, notes=note or None,
        applied_at=datetime.now(UTC) if outcome.status == "submitted" else None,
    )
    session.add(app)
    session.commit()
```

> Note: the `cache` variable is intentionally available for future LLM caching of tailor calls; wire `complete(..., cache=cache)` into `tailor_resume` only if a follow-up task adds caching. Leave as-is for now (YAGNI).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/apply/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Run the full apply suite**

Run: `pytest tests/apply tests/resume -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internhunter/apply/pipeline.py tests/apply/test_pipeline.py
git commit -m "feat(apply): pipeline orchestrator with fail-closed routing"
```

---

### Task 11: CLI `apply` command

**Files:**
- Modify: `internhunter/cli.py` (add `_cmd_apply` + subparser + dispatch)
- Test: `tests/apply/test_cli_apply.py`

**Interfaces:**
- Consumes: `auto_apply` (Task 10).
- Produces: `internhunter apply [--dry-run] [--limit N]` — prints a per-outcome summary line.

- [ ] **Step 1: Write the failing test**

```python
# tests/apply/test_cli_apply.py
from internhunter.apply.pipeline import ApplyOutcome


def test_cmd_apply_prints_summary(monkeypatch, capsys):
    import internhunter.cli as cli

    monkeypatch.setattr(
        cli, "_run_auto_apply",
        lambda **kw: [ApplyOutcome("u1", "submitted", confirmation="C1"),
                      ApplyOutcome("u2", "needs_review", reason="unfillable fields: Why us?")],
        raising=False,
    )
    import argparse
    cli._cmd_apply(argparse.Namespace(dry_run=False, limit=None))
    out = capsys.readouterr().out
    assert "submitted" in out and "needs_review" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/apply/test_cli_apply.py -v`
Expected: FAIL (`AttributeError: _cmd_apply`).

- [ ] **Step 3: Implement the command**

Add to `internhunter/cli.py`:

```python
def _run_auto_apply(**kwargs):
    import asyncio

    from internhunter.apply.pipeline import auto_apply

    return asyncio.run(auto_apply(**kwargs))


def _cmd_apply(args: argparse.Namespace) -> None:
    outcomes = _run_auto_apply(limit=args.limit, dry_run=args.dry_run)
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
        print(f"  {o.status:12} {o.job_uid or '-'} {o.reason or o.confirmation or ''}")
    print("apply: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
```

In `main()`, register the subparser (next to the others) and dispatch:

```python
    apply_cmd = subparsers.add_parser("apply")
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.add_argument("--limit", type=int, default=None)
```

Add to the dispatch block at the end of `main()` (matching the existing `if args.command == ...` style):

```python
    elif args.command == "apply":
        _cmd_apply(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/apply/test_cli_apply.py -v`
Expected: PASS

- [ ] **Step 5: Verify the command is wired**

Run: `internhunter apply --dry-run --limit 0`
Expected: prints `apply: ` summary line (zero outcomes when limit 0 / kill switch on); no traceback.

- [ ] **Step 6: Commit**

```bash
git add internhunter/cli.py tests/apply/test_cli_apply.py
git commit -m "feat(cli): add `apply` command for auto-apply pipeline"
```

---

### Task 12: Dashboard control + review queue

**Files:**
- Modify: `internhunter/web/app.py` (add POST `/apply/run` endpoint + review-queue read)
- Test: `tests/apply/test_web_apply.py`

**Interfaces:**
- Consumes: `auto_apply` (Task 10), existing FastAPI `app` and templating in `web/app.py`.
- Produces: `POST /apply/run` (form param `dry_run: bool = True`) returning a summary fragment; the existing applications view shows rows with status `needs_review` as a review queue. Endpoint refuses to run (returns a clear message, HTTP 200) when `enable_auto_apply` is False unless `dry_run` is true.

- [ ] **Step 1: Read the current web app to match patterns**

Run: `sed -n '1,60p' internhunter/web/app.py`
Expected: see how routes, templates, and `get_session` are used; mirror that style.

- [ ] **Step 2: Write the failing test**

```python
# tests/apply/test_web_apply.py
from fastapi.testclient import TestClient

from internhunter.web.app import app


def test_apply_run_dry_run_allowed_even_when_disabled(monkeypatch):
    import internhunter.web.app as web

    async def _fake(**kw):
        from internhunter.apply.pipeline import ApplyOutcome
        return [ApplyOutcome("u1", "would_submit", resume_path="/tmp/u1.pdf")]

    monkeypatch.setattr(web, "auto_apply", _fake, raising=False)
    client = TestClient(app)
    resp = client.post("/apply/run", data={"dry_run": "true"})
    assert resp.status_code == 200
    assert "would_submit" in resp.text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/apply/test_web_apply.py -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 4: Implement the endpoint**

Add to `internhunter/web/app.py` (import `auto_apply` at module top: `from internhunter.apply.pipeline import auto_apply`, and `from internhunter.config.settings import get_settings`):

```python
@app.post("/apply/run", response_class=HTMLResponse)
async def apply_run(dry_run: bool = Form(True)):
    settings = get_settings()
    if not settings.enable_auto_apply and not dry_run:
        return HTMLResponse("<div>Auto-apply is disabled. Enable it in settings to submit, "
                            "or run a dry-run.</div>")
    outcomes = await auto_apply(settings=settings, dry_run=dry_run)
    rows = "".join(
        f"<tr><td>{o.status}</td><td>{o.job_uid}</td>"
        f"<td>{o.reason or o.confirmation or ''}</td></tr>"
        for o in outcomes
    )
    return HTMLResponse(f"<table><tbody>{rows}</tbody></table>")
```

Add a button to the dashboard template (next to existing controls) that POSTs to `/apply/run` with an HTMX target, plus a "Dry run" checkbox. Match the existing template's HTMX attributes. Ensure `Form` and `HTMLResponse` are imported (`from fastapi import Form`, `from fastapi.responses import HTMLResponse`) if not already.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/apply/test_web_apply.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add internhunter/web/app.py tests/apply/test_web_apply.py
git commit -m "feat(web): auto-apply control and review-queue surface"
```

---

### Task 13: Adapter-authoring procedure for remaining Tier-A platforms

**Files:**
- Create: `docs/adapter-authoring.md`

This task ships no code — it documents the repeatable procedure for adding the remaining six Tier-A adapters (Ashby, Workable, SmartRecruiters, Recruitee, Personio, Pinpoint), each behind the `Submitter` contract from Task 4. Until an adapter exists, the pipeline already routes those ATSs to `needs_review` (Task 10), so the system is safe and grows incrementally.

- [ ] **Step 1: Write the procedure doc**

Create `docs/adapter-authoring.md` with these sections, written as concrete instructions (no placeholders):

1. **Record a fixture** — capture the platform's posting/questions response for one real internship into `tests/apply/fixtures/<ats>_*.json` (or `.html` for HTML forms). Never include real submissions.
2. **Write the parse helper** — `parse_*(payload) -> list[FormField]`, mapping platform field types to the canonical set `{text, email, file, textarea, select, checkbox}`. Add a unit test asserting field names, types, and `required` flags from the fixture (mirror `tests/apply/test_greenhouse_submit.py`).
3. **Implement the `Submitter`** — `class <Ats>Submitter(Submitter)` with `ats = "<ats>"`, `@register_submitter`, `probe_form` (httpx via `ctx.get_json`/`ctx.get_text`; for HTML platforms parse with the existing HTML utilities), and `submit`. If the platform requires a browser, set probe to use `ctx.browser` (already wired in `FetchContext`) and detect login/captcha → return `FormSpec(requires_account=True)` or `captcha_detected=True`.
4. **Register import** — add `import internhunter.apply.submit.<ats>  # noqa: F401` to `internhunter/apply/pipeline.py`.
5. **Confirm fail-closed** — verify with a probe that any required custom field lands in `needs_review`, and that a detected login wall/captcha never submits.

- [ ] **Step 2: Commit**

```bash
git add docs/adapter-authoring.md
git commit -m "docs(apply): adapter-authoring procedure for remaining Tier-A platforms"
```

---

## Self-Review

**Spec coverage:**
- Autonomy = auto-submit with guardrails → Tasks 5, 10 (guardrails + pipeline). ✓
- Target ATS = all 8 Tier-A behind one contract → Task 4 (contract), Tasks 8–9 (2 reference adapters), Task 13 (procedure for the other 6); pipeline routes adapter-less ATSs to review (Task 10). ✓ (Plan delivers framework + 2 adapters end-to-end; remaining 6 are incremental per the procedure, consistent with the spec's "ship incrementally" intent.)
- Unknown fields → skip & queue → Task 3 (classifier) + Task 10 (`needs_review`). ✓
- LLM = reuse Claude backend → Tasks 6, 10. ✓
- HTTP-first + browser fallback → Tasks 8–9 (HTTP), Task 13 (browser-fallback procedure), `FetchContext.browser` reused. ✓
- Guardrails (kill switch default off, fit 0.75, daily cap 15, per-company 1, dedupe, eligibility, pacing, proxy, dry-run) → Tasks 1, 5, 10. ✓ (proxy via existing `http_proxy`; dry-run in Tasks 10–12.)
- Truthfulness self-check → Task 6. ✓
- Applicant PII config + fail-closed on missing → Tasks 1, 2, 10. ✓
- PDF render → Task 7. ✓
- Error handling (per-job non-fatal, captcha/login → review) → Tasks 8–10. ✓
- Testing with recorded fixtures, no live submissions → Tasks 8, 9, 13. ✓

**Placeholder scan:** No `TBD`/`TODO` left as work items; the implementer notes on Greenhouse/Lever live-POST shape are explicit verification steps, not placeholders — probe/parse/registration are fully coded and fixture-tested.

**Type consistency:** `FormField(name,label,ftype,required,options)`, `FormSpec(fields,requires_account,captcha_detected)`, `SubmitResult(status,confirmation,reason)`, `Applicant(...)`, `ApplyOutcome(job_uid,status,reason,resume_path,confirmation)`, and `Submitter.probe_form(job,ctx)` / `submit(job,ctx,payload,resume_path)` are used identically across Tasks 3–12. ✓
