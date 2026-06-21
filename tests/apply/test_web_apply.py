from pathlib import Path

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


def test_apply_run_real_refused_when_disabled(monkeypatch):
    """Real (non-dry) run must be rejected when enable_auto_apply is False (the default)."""
    import internhunter.web.app as web

    called = []

    async def _should_not_be_called(**kw):
        called.append(True)
        from internhunter.apply.pipeline import ApplyOutcome
        return [ApplyOutcome("u1", "submitted", resume_path="/tmp/u1.pdf")]

    monkeypatch.setattr(web, "auto_apply", _should_not_be_called, raising=False)
    client = TestClient(app)
    # dry_run absent / "false" -> Form(True) default does NOT apply; value "false" sends False
    resp = client.post("/apply/run", data={"dry_run": "false"})
    assert resp.status_code == 200
    assert "disabled" in resp.text
    assert called == [], "auto_apply must NOT be called when enable_auto_apply is False"


def test_dashboard_has_apply_button():
    """The dashboard template must contain the HTMX auto-apply button wiring."""
    template_path = (
        Path(__file__).parent.parent.parent
        / "internhunter" / "web" / "templates" / "index.html"
    )
    content = template_path.read_text()
    assert 'hx-post="/apply/run"' in content
