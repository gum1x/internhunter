from __future__ import annotations

from internhunter.apply.fields import FormField
from internhunter.apply.submit.base import (
    FormSpec,
    SubmitResult,
    Submitter,
    register_submitter,
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
