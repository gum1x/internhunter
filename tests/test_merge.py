from __future__ import annotations

from sqlalchemy.orm import Session

from internhunter.core.db import Board
from internhunter.discovery.merge import merge_boards, retire_failing_boards
from internhunter.sources.base import BoardRef


def test_merge_inserts_new_and_dedupes(db_session: Session) -> None:
    refs = [
        BoardRef(ats="greenhouse", token="zzznewco1", company="New Co 1"),
        BoardRef(ats="greenhouse", token="zzznewco1", company="dup"),
        BoardRef(ats="lever", token="zzznewco2"),
    ]
    result = merge_boards(refs, session=db_session, append_registry=False)
    assert result.discovered == 2
    assert result.new_boards == 2
    assert result.existing == 0

    again = merge_boards(refs, session=db_session, append_registry=False)
    assert again.new_boards == 0
    assert again.existing == 2


def test_retire_failing_boards(db_session: Session) -> None:
    db_session.add(Board(ats="lever", token="flaky", consecutive_failures=8, status="active"))
    db_session.add(Board(ats="lever", token="healthy", consecutive_failures=1, status="active"))
    db_session.commit()

    retired = retire_failing_boards(db_session, threshold=6)
    assert retired == 1
    healthy = db_session.query(Board).filter_by(token="healthy").one()
    assert healthy.status == "active"
