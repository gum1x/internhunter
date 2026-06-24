from internhunter.apply.submit.base import (
    FormSpec,
    SubmitResult,
    Submitter,
    get_submitter,
    register_submitter,
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
