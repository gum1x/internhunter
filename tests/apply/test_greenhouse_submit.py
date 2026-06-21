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
