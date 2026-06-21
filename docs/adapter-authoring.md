# Adapter-Authoring Procedure for Tier-A ATS Platforms

This guide documents the repeatable procedure for implementing a `Submitter` adapter for any ATS platform (Ashby, Workable, SmartRecruiters, Recruitee, Personio, Pinpoint). Each adapter enables auto-submit for that platform; until it exists, the pipeline routes jobs to `needs_review` (fail-closed).

## Step 1: Record a Fixture

Capture the ATS platform's form response into a fixture file. This becomes the test input and reference documentation for your adapter.

**Process:**

1. Find a real internship posting on the target platform (e.g., Ashby careers board).
2. Identify the endpoint that returns the form schema (API response or rendered HTML). Use your browser's network inspector.
3. For **API-based platforms** (most Tier-A vendors), capture the JSON response into `tests/apply/fixtures/<ats>_job_form.json` (e.g., `ashby_job_form.json`). Include a minimal but realistic posting with at least:
   - One text field (e.g., name, email)
   - One file field (resume/CV)
   - One open-ended field (textarea or text area question)
   - One conditional/select field if the platform uses them
4. For **HTML form platforms**, render the form to `tests/apply/fixtures/<ats>_form.html`.
5. **Never include real submissions, credentials, or PII** in fixtures. Sanitize names, emails, and custom question text if needed.

**Example fixture structure (Ashby JSON):**
```json
{
  "fields": [
    {"id": "email", "label": "Email", "type": "email", "required": true},
    {"id": "resume", "label": "Resume", "type": "file", "required": true},
    {"id": "reason", "label": "Why Ashby?", "type": "textarea", "required": false}
  ]
}
```

## Step 2: Write the Parse Helper

Implement a `parse_<ats>(payload) -> list[FormField]` function that maps the platform's field types to the canonical FormField types.

**Canonical FormField types:**
- `text` — single-line text input (name, email, phone, URL)
- `email` — email input (most platforms accept via text)
- `file` — file upload (resume, portfolio, etc.)
- `textarea` — multi-line text
- `select` — dropdown or single-select
- `checkbox` — boolean/multi-value
- `options` — tuple of choices (populated for select/checkbox)

**Implementation:**

1. Create a type-mapping dict from the platform's field types to canonical types:
   ```python
   _TYPE_MAP = {
       "email": "email",
       "file": "file",
       "textarea": "textarea",
       "select": "select",
       # ... platform-specific type names
   }
   ```
2. Iterate over the platform's fields/questions and construct `FormField` objects:
   ```python
   def parse_ashby(payload: dict) -> list[FormField]:
       out: list[FormField] = []
       for field in payload.get("fields", []):
           out.append(
               FormField(
                   name=field.get("id", ""),
                   label=field.get("label", ""),
                   ftype=_TYPE_MAP.get(field.get("type", ""), "text"),
                   required=bool(field.get("required")),
                   options=tuple(field.get("options", [])) if field.get("type") == "select" else (),
               )
           )
       return out
   ```

**Testing the parser:**

Write a unit test in `tests/apply/test_<ats>_submit.py` that validates the parser against your fixture:

```python
import json
from pathlib import Path
from internhunter.apply.submit.<ats> import parse_<ats>

FIX = Path(__file__).parent / "fixtures" / "<ats>_job_form.json"

def test_parse_fields_maps_types_and_required():
    payload = json.loads(FIX.read_text())
    fields = parse_<ats>(payload)
    by_name = {f.name: f for f in fields}
    
    # Assert field names, types, and required flags match fixture expectations
    assert by_name["resume"].ftype == "file"
    assert by_name["email"].ftype == "email" or by_name["email"].ftype == "text"
    assert by_name["email"].required is True
```

Run `pytest tests/apply/test_<ats>_submit.py -v` to verify.

## Step 3: Implement the Submitter Class

Create `internhunter/apply/submit/<ats>.py` with a `Submitter` subclass that probes the form and submits applications.

**Contract (from `internhunter/apply/submit/base.py`):**

```python
class Submitter(ABC):
    ats: str  # platform identifier (lowercase)
    
    async def probe_form(self, job, ctx) -> FormSpec:
        """Fetch the form schema for a job. Return FormSpec with fields, 
        optionally set requires_account=True or captcha_detected=True if 
        a login wall or CAPTCHA is encountered."""
    
    async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult:
        """Submit an application. Return SubmitResult with status 
        ('submitted', 'failed'), optional confirmation ID, and reason (on failure)."""
```

**Implementation template:**

```python
from internhunter.apply.fields import FormField
from internhunter.apply.submit.base import (
    FormSpec, SubmitResult, Submitter, register_submitter,
)

_TYPE_MAP = {
    # Map platform field types to canonical types
    "email": "email",
    "file": "file",
    "textarea": "textarea",
    "select": "select",
}

def parse_<ats>(payload: dict) -> list[FormField]:
    # (From Step 2)
    ...

@register_submitter
class <AtsName>Submitter(Submitter):
    ats = "<ats>"  # e.g., "ashby"
    
    def _job_url(self, job) -> str:
        """Construct the API endpoint for probing or posting."""
        # Most platforms use job.board_token and job.source_job_id
        return f"https://api.example.com/v1/{job.board_token}/jobs/{job.source_job_id}"
    
    async def probe_form(self, job, ctx) -> FormSpec:
        """Fetch form schema; detect login walls and CAPTCHAs."""
        try:
            payload = await ctx.get_json(self._job_url(job))
            payload = payload if isinstance(payload, dict) else {}
        except Exception:
            # If fetch fails, return empty form (pipeline routes to needs_review)
            return FormSpec(fields=[])
        
        # Check for login wall (e.g., 401 Unauthorized, redirect to /login)
        if payload.get("requires_login"):
            return FormSpec(fields=[], requires_account=True)
        
        # Check for CAPTCHA (platform-specific; e.g., captcha_token required)
        if payload.get("captcha_required"):
            return FormSpec(fields=[], captcha_detected=True)
        
        return FormSpec(fields=parse_<ats>(payload))
    
    async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult:
        """Submit the application payload."""
        body = {k: v for k, v in payload.items() if v != "@resume"}
        
        try:
            resp = await ctx.post_json(self._job_url(job), json_body=body)
        except Exception as exc:
            # Network/HTTP errors are non-fatal and recorded by the pipeline
            return SubmitResult(status="failed", reason=f"post error: {exc}")
        
        # Validate success based on platform response
        if isinstance(resp, dict) and (resp.get("success") or resp.get("status") == "ok"):
            return SubmitResult(
                status="submitted",
                confirmation=str(resp.get("id") or resp.get("application_id") or "")
            )
        
        return SubmitResult(
            status="failed",
            reason=f"unexpected response: {resp!r:.200}"
        )
```

**Key patterns:**

- Use `@register_submitter` decorator to auto-register the class in the submitter registry.
- Use `ctx.get_json(url)` to fetch JSON endpoints; `ctx.get_text(url)` for HTML.
- Use `ctx.post_json(url, json_body=body)` to submit; catches network errors automatically.
- For **HTML form platforms** (less common for Tier-A): parse with `ctx.get_text()`, then use existing HTML utilities (e.g., BeautifulSoup or regex) to extract form fields.
- For **browser-based platforms** (if needed): use `ctx.browser` (a `BrowserFactory` already wired in `FetchContext`). Detect login/captcha by inspecting page state, then set `requires_account=True` or `captcha_detected=True` in the returned `FormSpec`.
- Always catch exceptions in `probe_form` and `submit` to prevent pipeline crashes.

## Step 4: Register the Adapter

Add an import to `internhunter/apply/pipeline.py` to trigger registration:

```python
import internhunter.apply.submit.<ats>  # noqa: F401  (registration)
```

This import must come after the existing Greenhouse/Lever imports. The `@register_submitter` decorator in your adapter class will populate the registry. The `# noqa: F401` comment suppresses the linter's unused-import warning (the side effect—registration—is the point).

**Verification:**

Add a test to `tests/apply/test_<ats>_submit.py`:

```python
def test_submitter_registered():
    from internhunter.apply.submit.base import get_submitter
    import internhunter.apply.submit.<ats>  # noqa: F401
    assert isinstance(get_submitter("<ats>"), <AtsName>Submitter)
```

Run `pytest tests/apply/test_<ats>_submit.py::test_submitter_registered -v` to verify.

## Step 5: Confirm Fail-Closed Behavior

Verify that your adapter fails safely and does not skip critical checks:

1. **Test with a required custom field (unfillable by the system):**
   - Create a fixture that includes a custom field the system cannot populate (e.g., "Custom experience level" not in the `Applicant` model).
   - Run the pipeline probe for that job.
   - Verify the field lands in `unknown` and the job is routed to `needs_review` (not submitted).

2. **Test login wall / CAPTCHA detection:**
   - Mock or spy on `ctx.get_json` to return a response with `requires_login: true` or `captcha_required: true`.
   - Verify that `probe_form` returns `FormSpec(requires_account=True)` or `captcha_detected=True`.
   - Verify the pipeline routes the job to `needs_review` (not submitted).

3. **Test network error handling:**
   - Mock `ctx.get_json` or `ctx.post_json` to raise an exception.
   - Verify `probe_form` returns an empty `FormSpec` (or handles gracefully).
   - Verify `submit` returns `SubmitResult(status="failed", reason=...)`.
   - Verify the pipeline records the failure and does not retry indefinitely.

**Example test (conftest or test file):**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_ashby_detects_login_wall():
    from internhunter.apply.submit.ashby import AshbySubmitter
    
    submitter = AshbySubmitter()
    job = MagicMock(board_token="test", source_job_id="123")
    ctx = MagicMock()
    ctx.get_json = AsyncMock(return_value={"requires_login": True})
    
    spec = await submitter.probe_form(job, ctx)
    assert spec.requires_account is True
```

---

## Checklist

- [ ] Fixture recorded at `tests/apply/fixtures/<ats>_job_form.json` (or `.html`)
- [ ] Parse function `parse_<ats>` maps all platform field types to canonical types
- [ ] Parser unit test in `tests/apply/test_<ats>_submit.py` validates types and required flags
- [ ] `<AtsName>Submitter` class with `@register_submitter`, `probe_form`, `submit` implemented
- [ ] `probe_form` handles login walls and CAPTCHAs (returns `FormSpec` with appropriate flags)
- [ ] `submit` catches exceptions and returns `SubmitResult(status="submitted"|"failed", ...)`
- [ ] Import added to `internhunter/apply/pipeline.py` with `# noqa: F401` comment
- [ ] Registration test passes: `get_submitter("<ats>")` returns the submitter instance
- [ ] Fail-closed tests: unfillable fields route to `needs_review`, login walls return early
- [ ] All parser and registration tests pass: `pytest tests/apply/test_<ats>_submit.py -v`
- [ ] Existing tests still pass: `pytest tests/apply/ -v` (no regressions)

---

## Reference Implementations

- **Greenhouse** (`internhunter/apply/submit/greenhouse.py`, `tests/apply/test_greenhouse_submit.py`): JSON API with questions, type mapping, fixture-based test.
- **Lever** (`internhunter/apply/submit/lever.py`): Similar JSON API, slightly different schema (applicationQuestions vs. questions).

Both use `ctx.get_json` for probe, `ctx.post_json` for submit, and `@register_submitter` for registration.
