# Auto-Apply + Per-Job Resume Optimizer — Design

**Date:** 2026-06-20
**Status:** Approved (design); pending implementation plan
**Component:** `internhunter/apply/` (new), `internhunter/resume/tailor.py` (implement stub), `internhunter/web/` (dashboard control)

## Summary

A one-action feature that, for high-fit Tier-A internships, tailors the candidate's
resume to each job, fills the application form, and **auto-submits with guardrails** —
while skipping (and queuing for manual review) any job whose form contains fields the
system cannot fill confidently from the candidate's profile.

This is the riskier "auto-submit" path (chosen deliberately over a review-gate path),
so the design's job is to make the guardrails real: applications go out under the
candidate's real name and email, and many ATS ToS discourage automated submission.
Safety defaults are conservative and the master switch is **off** by default.

## Scope decisions (locked)

- **Autonomy:** auto-submit with guardrails (not review-gate, not tailor-only).
- **Target ATS:** all 8 Tier-A keyless platforms — Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Recruitee, Personio, Pinpoint — each behind a common adapter
  contract so they ship incrementally.
- **Unknown fields:** skip & queue. Auto-submit only when *every required field* is
  fillable from the profile or is a standard resume/contact upload. Any custom screening
  question, required cover letter, or unrecognized required field → `needs_review`.
- **LLM:** reuse the existing Claude `llm/` backend (`claude-opus-4-8`). No new stack.
- **Transport:** HTTP-first per adapter, Playwright/CloakBrowser fallback (Approach A),
  mirroring the codebase's existing httpx-first / browser-for-hard-cases philosophy.

## Architecture (Approach A)

HTTP-first submission adapters with browser fallback, behind one `Submitter` interface.
Several Tier-A ATSs expose an observable application POST (Greenhouse board API; Lever
postings apply endpoint) — use httpx there. For platforms that use tokens/anti-CSRF/
captcha or no clean POST, drive the existing Playwright/CloakBrowser stack. Each ATS is
one adapter implementing the same contract, so platforms are added/maintained
independently and failures are isolated per-platform.

Rejected alternatives:
- **Pure browser for all 8** — uniform but slow, brittle, captcha-prone where unneeded.
- **Pure HTTP for all 8** — fastest but silently fails on platforms with tokens/captcha.

## Components

```
internhunter/apply/
  __init__.py
  pipeline.py        # orchestrator: select → guardrail → probe → classify → tailor → render → submit → record
  applicant.py       # loads applicant PII/identity from profile.yaml, validates completeness
  fields.py          # FormField model + classifier: "known" (fillable) vs "unknown" (custom)
  guardrails.py      # fit threshold, daily cap, per-company cap, dedup, kill switch, eligibility
  render.py          # tailored text → clean single-column ATS-parseable PDF
  submit/
    base.py          # Submitter ABC
    greenhouse.py    # httpx adapter (documented board application POST)
    lever.py         # httpx adapter (postings apply endpoint)
    ashby.py / workable.py / smartrecruiters.py / recruitee.py / personio.py / pinpoint.py
                     # httpx where possible, Playwright/CloakBrowser fallback
```

Plus:
- `internhunter/resume/tailor.py` — implement the stubbed `tailor_resume()` + truthfulness self-check.
- `internhunter/web/` — dashboard "Auto-apply" control + endpoint, review-queue view, runtime stop.
- `internhunter/config/profile.yaml` — new `applicant:` section (PII).
- `internhunter/config/settings.py` — new guardrail settings.

### `Submitter` contract (`submit/base.py`)

```python
class FormSpec:
    fields: list[FormField]          # everything the form requires
    requires_account: bool           # login wall detected
    captcha_detected: bool

class SubmitResult:
    status: str                      # "submitted" | "failed" | "needs_review"
    confirmation: str | None         # confirmation id/url if available
    reason: str | None               # failure/skip reason

class Submitter(ABC):
    ats: str
    def probe_form(self, job) -> FormSpec: ...
    def submit(self, job, payload) -> SubmitResult: ...
```

The `probe` / `submit` split is what enables "skip & queue unknown fields": we probe and
classify *before* any submission, and only submit when the classifier passes.

## Data flow

1. **Select** — `jobs` where `is_internship`, fit/discovery_score ≥ threshold, ATS ∈ Tier-A,
   not already in `applications`, not confirmed slop.
2. **Guardrail gate** — kill switch, eligibility (work-auth vs sponsorship signal),
   daily cap, per-company cap, dedup.
3. **Probe** — `Submitter.probe_form(job)` → `FormSpec`.
4. **Classify** — login wall / captcha / any required unknown field → `needs_review`
   (stop). Otherwise auto-path.
5. **Tailor** — `tailor_resume()` → job-specific resume; truthfulness self-check verifies
   every bullet traces to source. Reject → fall back to base resume + warn.
6. **Render** — tailored text → ATS-parseable single-column PDF.
7. **Submit** — `Submitter.submit()`.
8. **Record** — write `applications` row: status (`submitted` / `needs_review` / `failed`),
   `resume_path`, timestamps, confirmation/reason.

## Guardrails (settings.py, safe defaults)

- **Kill switch** — `enable_auto_apply: bool = False`. Master off by default. Runtime stop
  via dashboard button + sentinel file checked between every submission.
- **Fit threshold** — `auto_apply_min_fit: float = 0.75` (stricter than `notify_min_fit=0.6`).
- **Daily cap** — `auto_apply_daily_cap: int = 15`. Counts `submitted` rows in last 24h.
- **Per-company cap** — at most 1 auto-application per company.
- **Dedup** — never submit to a `job_uid` (or same company + normalized title) already in
  `applications`, any status.
- **Eligibility** — if `applicant.requires_sponsorship` and job signals "no sponsorship /
  citizen required" → `needs_review` (don't misrepresent or waste an application).
- **Pacing + proxy** — randomized inter-submission delay, submission per-host concurrency = 1,
  honor `HTTP_PROXY`/`HTTPS_PROXY`. This is deliberately slow; not a crawler.
- **Dry-run** — `--dry-run` runs tailor/render/probe/classify and records `would_submit`
  without posting, for auditing before arming.

## Resume truthfulness mechanism

1. `tailor_resume()` prompt embeds the existing `TRUTHFULNESS_CONTRACT` + `ATS_FORMAT_NOTES`.
2. **Self-check pass** — a second LLM call over (base, tailored) verifies, per bullet, that
   it traces to a real source bullet. Any unverifiable claim → reject the tailored resume.
3. Base resume is always the safe fallback; auto-submit never blocks on tailoring success.

## Applicant identity (`profile.yaml` `applicant:` section)

New required-for-apply fields: full name, email, phone, location/address, work-authorization
status, `requires_sponsorship` (bool), LinkedIn/GitHub/portfolio URLs, school, grad date.
`applicant.py` validates completeness; missing required PII disables auto-apply with a clear
message (fails closed).

## Error handling

- Probe/submit failures are non-fatal per job → `failed` + reason; pipeline continues.
- Captcha/login wall during probe → `needs_review`, never a blind submit.
- Network/proxy errors use the existing retry policy.

## Testing (TDD)

- Each `Submitter` adapter against **recorded form fixtures** (saved HTML/JSON probe
  responses). **No live submissions in tests.**
- Guardrails: cap math, dedup, eligibility, kill switch.
- Field classifier: real-world form variants (known vs unknown fields).
- Truthfulness self-check: known-fabrication fixture must be rejected.
- End-to-end pipeline in `--dry-run` against fixtures.

## Out of scope (this iteration)

- Tier-B/C ATS platforms.
- Account-creating multi-step wizards (Workday/iCIMS/Oracle).
- LLM-generated answers to custom screening questions (those jobs go to review queue).
- Cover-letter generation.
