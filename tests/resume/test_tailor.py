from internhunter.resume.tailor import TailorRequest, tailor_resume


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
