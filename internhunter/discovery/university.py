"""University career portals (the keyless slice).

Most student job portals (Symplicity / 12twenty / Handshake) are login-gated, so we can't poll
their internal listings. The keyless win is the *public* career pages many schools publish:
they embed employer ATS links and schema.org ``JobPosting`` data. For each seed URL we reuse
the existing JSON-LD harvester to recover the real ATS boards behind those postings and feed
them into the registry — after which the normal poller picks them up.

The seed list lives at ``registry/universities.jsonl`` and is meant to be user-extended with
their own school's public board.
"""
from __future__ import annotations

import json
from pathlib import Path

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import init_db
from internhunter.core.fetch import build_fetch_context
from internhunter.discovery.fingerprint import Detection, detection_to_board_ref
from internhunter.discovery.jsonld import discover_from_jsonld
from internhunter.discovery.merge import merge_boards

_DEFAULT_LIST = Path(__file__).resolve().parent.parent / "registry" / "universities.jsonl"


def load_university_urls(path: Path | None = None) -> list[str]:
    target = path or _DEFAULT_LIST
    if not target.exists():
        return []
    urls: list[str] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = record.get("url") if isinstance(record, dict) else None
        if isinstance(url, str) and url.startswith("http"):
            urls.append(url)
    return urls


async def ingest_universities(settings: Settings | None = None) -> tuple[int, int, int]:
    """Harvest ATS boards behind public university career pages. Returns
    (urls_examined, jobs, new_boards) — jobs is always 0 (we recover boards, not listings)."""
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    urls = load_university_urls(getattr(resolved, "university_list_path", None))
    if not urls:
        return 0, 0, 0

    detections: list[Detection] = []
    seen: set[tuple[str, str]] = set()
    async with build_fetch_context(resolved) as ctx:
        for url in urls:
            try:
                found = await discover_from_jsonld(ctx, url)
            except Exception:
                ctx.logger.debug("university harvest failed for {}", url)
                continue
            for det in found:
                key = (det.ats, det.token)
                if key in seen:
                    continue
                seen.add(key)
                detections.append(det)

    boards = merge_boards([detection_to_board_ref(d) for d in detections])
    return len(urls), 0, boards.new_boards
