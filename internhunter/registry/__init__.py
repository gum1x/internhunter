from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from internhunter.sources.base import BoardRef

_BOARDS_PATH = Path(__file__).parent / "boards.jsonl"


def _iter_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with _BOARDS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            records.append(json.loads(stripped))
    return records


def load_boards(ats: str | None = None) -> list[BoardRef]:
    boards: list[BoardRef] = []
    for record in _iter_records():
        record_ats = str(record["ats"])
        if ats is not None and record_ats != ats:
            continue
        tags = record.get("tags", [])
        boards.append(
            BoardRef(
                ats=record_ats,
                token=str(record["token"]),
                company=record.get("company"),
                extra={"tags": list(tags)},
            )
        )
    return boards


def registry_stats() -> dict[str, int]:
    counts = Counter(str(record["ats"]) for record in _iter_records())
    stats: dict[str, int] = dict(counts)
    stats["total"] = sum(counts.values())
    return stats
