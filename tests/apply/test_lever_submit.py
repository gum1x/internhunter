import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from internhunter.apply.submit.lever import LeverSubmitter, parse_posting

FIX = Path(__file__).parent / "fixtures" / "lever_posting.json"


def test_parse_posting_extracts_fields():
    fields = parse_posting(json.loads(FIX.read_text()))
    by_name = {f.name: f for f in fields}
    assert by_name["resume"].ftype == "file"
    assert by_name["card_0"].ftype == "textarea"
    assert by_name["email"].required is True


def test_submitter_registered():
    import internhunter.apply.submit.lever  # noqa: F401
    from internhunter.apply.submit.base import get_submitter

    assert isinstance(get_submitter("lever"), LeverSubmitter)


class _FakeCtx:
    def __init__(self, response: Any) -> None:
        self._response = response

    async def post_json(self, url: str, *, json_body: Any) -> Any:
        return self._response


_JOB = SimpleNamespace(board_token="acme", source_job_id="j1")
_SUBMITTER = LeverSubmitter()


def test_submit_ok_true_is_submitted():
    ctx = _FakeCtx({"ok": True, "id": "x"})
    result = asyncio.run(_SUBMITTER.submit(_JOB, ctx, {}, None))
    assert result.status == "submitted"
    assert result.confirmation == "x"


def test_submit_ambiguous_no_ok_is_failed():
    ctx = _FakeCtx({"error": "bad"})
    result = asyncio.run(_SUBMITTER.submit(_JOB, ctx, {}, None))
    assert result.status == "failed"


def test_submit_ok_false_is_failed():
    ctx = _FakeCtx({"ok": False})
    result = asyncio.run(_SUBMITTER.submit(_JOB, ctx, {}, None))
    assert result.status == "failed"
