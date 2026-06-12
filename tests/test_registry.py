from __future__ import annotations

from internhunter.registry import load_boards, registry_stats
from internhunter.sources.base import BoardRef

KNOWN_ATS = {
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "recruitee",
    "personio",
}


def test_load_boards_returns_many() -> None:
    boards = load_boards()
    assert len(boards) >= 140
    assert all(isinstance(board, BoardRef) for board in boards)


def test_pairs_are_unique() -> None:
    pairs = [(board.ats, board.token) for board in load_boards()]
    assert len(pairs) == len(set(pairs))


def test_all_ats_known() -> None:
    assert all(board.ats in KNOWN_ATS for board in load_boards())


def test_filter_by_ats() -> None:
    greenhouse = load_boards(ats="greenhouse")
    assert len(greenhouse) > 0
    assert all(board.ats == "greenhouse" for board in greenhouse)


def test_tags_in_extra() -> None:
    board = load_boards()[0]
    assert board.extra is not None
    assert "tags" in board.extra


def test_registry_stats_total() -> None:
    assert registry_stats()["total"] == len(load_boards())
