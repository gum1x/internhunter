from internhunter.apply.pipeline import ApplyOutcome


def test_cmd_apply_prints_summary(monkeypatch, capsys):
    import internhunter.cli as cli

    monkeypatch.setattr(
        cli, "_run_auto_apply",
        lambda **kw: [ApplyOutcome("u1", "submitted", confirmation="C1"),
                      ApplyOutcome("u2", "needs_review", reason="unfillable fields: Why us?")],
        raising=False,
    )
    import argparse
    cli._cmd_apply(argparse.Namespace(dry_run=False, limit=None))
    out = capsys.readouterr().out
    assert "submitted" in out and "needs_review" in out
