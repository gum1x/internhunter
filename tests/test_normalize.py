from __future__ import annotations

from datetime import UTC, datetime

from internhunter.core.normalize import parse_datetime


def test_parse_datetime_handles_hostile_numeric_overflow() -> None:
    # A hostile epoch value must yield None, not crash the ingest channel.
    assert parse_datetime(1e20) is None
    assert parse_datetime(-1e20) is None
    assert parse_datetime("9" * 40) is None


def test_parse_datetime_normal_values_still_work() -> None:
    assert parse_datetime(0) == datetime(1970, 1, 1, tzinfo=UTC)
    assert parse_datetime("2026-05-01T00:00:00Z") is not None
    assert parse_datetime(None) is None
    assert parse_datetime("") is None
