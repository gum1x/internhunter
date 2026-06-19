from __future__ import annotations

from datetime import datetime, timedelta

from internhunter.match.rarity import discovery_score, freshness_score, rarity_score


def test_freshness_now_is_one() -> None:
    now = datetime(2026, 1, 1)
    assert abs(freshness_score(now, now) - 1.0) < 1e-9


def test_freshness_half_life_is_half() -> None:
    now = datetime(2026, 1, 1)
    posted = now - timedelta(days=14)
    assert abs(freshness_score(posted, now, half_life_days=14.0) - 0.5) < 1e-9


def test_freshness_far_past_near_zero() -> None:
    now = datetime(2026, 1, 1)
    posted = now - timedelta(days=400)
    assert freshness_score(posted, now) < 0.01


def test_freshness_none_is_neutral() -> None:
    now = datetime(2026, 1, 1)
    assert freshness_score(None, now) == 0.3


def test_freshness_future_is_neutral_not_max() -> None:
    # A future post date is suspicious; it must not earn max freshness (which would
    # let a low-quality source post-date a listing to the top of the ranking).
    now = datetime(2026, 1, 1)
    posted = now + timedelta(days=5)
    score = freshness_score(posted, now)
    assert score < 1.0
    assert abs(score - 0.3) < 1e-9


def test_rarity_in_unit_interval() -> None:
    for n in range(0, 20):
        assert 0.0 <= rarity_score(n) <= 1.0
        assert 0.0 <= rarity_score(n, 100) <= 1.0


def test_rarity_decreasing_in_times_seen() -> None:
    values = [rarity_score(n) for n in range(0, 10)]
    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))


def test_rarity_decreasing_in_times_seen_with_board() -> None:
    values = [rarity_score(n, 100) for n in range(0, 10)]
    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))


def test_rarity_decreasing_in_board_size() -> None:
    values = [rarity_score(2, b) for b in (1, 10, 50, 200, 1000)]
    assert all(values[i] > values[i + 1] for i in range(len(values) - 1))


def test_rarity_small_board_boost() -> None:
    assert rarity_score(3, 1) > rarity_score(3)


def test_discovery_is_weighted_sum() -> None:
    score = discovery_score(0.8, 0.6, 0.4, w_fit=0.5, w_fresh=0.25, w_rarity=0.25)
    expected = 0.5 * 0.8 + 0.25 * 0.6 + 0.25 * 0.4
    assert abs(score - expected) < 1e-9


def test_discovery_normalizes_weights() -> None:
    score = discovery_score(0.8, 0.6, 0.4, w_fit=2.0, w_fresh=1.0, w_rarity=1.0)
    expected = (2.0 * 0.8 + 1.0 * 0.6 + 1.0 * 0.4) / 4.0
    assert abs(score - expected) < 1e-9


def test_discovery_in_unit_interval() -> None:
    assert discovery_score(1.0, 1.0, 1.0) == 1.0
    assert discovery_score(0.0, 0.0, 0.0) == 0.0
