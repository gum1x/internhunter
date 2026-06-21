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
