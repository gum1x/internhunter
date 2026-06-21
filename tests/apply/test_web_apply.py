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
