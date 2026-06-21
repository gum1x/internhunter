from __future__ import annotations

from typing import Any

from internhunter.apply.fields import FormField
from internhunter.apply.submit.base import (
    FormSpec,
    SubmitResult,
    Submitter,
    register_submitter,
)

_TYPE_MAP = {"text": "text", "file": "file", "textarea": "textarea", "select": "select"}


def parse_posting(payload: dict[str, Any]) -> list[FormField]:
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

    async def probe_form(self, job: Any, ctx: Any) -> FormSpec:
        url = f"https://api.lever.co/v0/postings/{job.board_token}/{job.source_job_id}"
        payload = await ctx.get_json(url)
        payload = payload if isinstance(payload, dict) else {}
        return FormSpec(fields=parse_posting(payload))

    async def submit(
        self, job: Any, ctx: Any, payload: dict[str, str], resume_path: Any
    ) -> SubmitResult:
        url = f"https://jobs.lever.co/{job.board_token}/{job.source_job_id}/apply"
        body = {k: v for k, v in payload.items() if v != "@resume"}
        try:
            resp = await ctx.post_json(url, json_body=body)
        except Exception as exc:
            return SubmitResult(status="failed", reason=f"post error: {exc}")
        if isinstance(resp, dict) and resp.get("ok", True):
            return SubmitResult(status="submitted", confirmation=str(resp.get("id") or ""))
        return SubmitResult(status="failed", reason=f"unexpected response: {resp!r:.200}")
