from internhunter.config.settings import Settings


def test_auto_apply_defaults_are_safe():
    s = Settings()
    assert s.enable_auto_apply is False          # kill switch off by default
    assert s.auto_apply_min_fit == 0.75
    assert s.auto_apply_daily_cap == 15
    assert s.auto_apply_per_company_cap == 1
    assert s.auto_apply_delay_seconds >= 0
