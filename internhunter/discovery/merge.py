from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.core.db import Board, get_session
from internhunter.registry import load_boards
from internhunter.sources.base import BoardRef

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry" / "boards.jsonl"


@dataclass
class MergeResult:
    discovered: int = 0
    new_boards: int = 0
    existing: int = 0
    new_refs: list[BoardRef] = field(default_factory=list)


def _dedupe(refs: list[BoardRef]) -> list[BoardRef]:
    seen: set[tuple[str, str]] = set()
    out: list[BoardRef] = []
    for ref in refs:
        key = (ref.ats, ref.token)
        if not ref.ats or not ref.token or key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _append_registry(refs: list[BoardRef]) -> None:
    if not refs:
        return
    lines = []
    for ref in refs:
        record = {"ats": ref.ats, "token": ref.token}
        if ref.company:
            record["company"] = ref.company
        tags = (ref.extra or {}).get("tags") if ref.extra else None
        if tags:
            record["tags"] = tags
        lines.append(json.dumps(record, ensure_ascii=False))
    with _REGISTRY_PATH.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def merge_boards(
    refs: list[BoardRef],
    session: Session | None = None,
    append_registry: bool = True,
) -> MergeResult:
    candidates = _dedupe(refs)
    known = {(r.ats, r.token) for r in load_boards()}

    owns_session = session is None
    active = session or get_session()
    result = MergeResult(discovered=len(candidates))
    try:
        for ref in candidates:
            key = (ref.ats, ref.token)
            if key in known:
                result.existing += 1
                continue
            existing_row = active.scalar(
                select(Board).where(Board.ats == ref.ats, Board.token == ref.token)
            )
            if existing_row is not None:
                result.existing += 1
                known.add(key)
                continue
            active.add(
                Board(
                    ats=ref.ats,
                    token=ref.token,
                    company=ref.company,
                    tags=(ref.extra or {}).get("tags", []) if ref.extra else [],
                    status="discovered",
                )
            )
            known.add(key)
            result.new_boards += 1
            result.new_refs.append(ref)
        active.commit()
    finally:
        if owns_session:
            active.close()

    if append_registry:
        _append_registry(result.new_refs)
    return result


def retire_failing_boards(session: Session, threshold: int = 6) -> int:
    rows = session.scalars(
        select(Board).where(
            Board.consecutive_failures >= threshold, Board.status != "retired"
        )
    ).all()
    for row in rows:
        row.status = "retired"
    session.commit()
    return len(rows)
