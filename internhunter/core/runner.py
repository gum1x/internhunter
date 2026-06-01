from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module

from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Board, get_session, init_db, upsert_jobs
from internhunter.core.dedup import collapse
from internhunter.core.fetch import build_fetch_context
from internhunter.core.models import NormalizedJob
from internhunter.registry import load_boards
from internhunter.sources.base import SOURCE_REGISTRY, BoardRef, Source


@dataclass
class BoardResult:
    ref: BoardRef
    jobs_found: int = 0
    internships: int = 0
    inserted: int = 0
    updated: int = 0
    error: str | None = None


@dataclass
class PollSummary:
    results: list[BoardResult] = field(default_factory=list)
    duplicates_merged: int = 0

    @property
    def boards_polled(self) -> int:
        return sum(1 for r in self.results if r.error is None)

    @property
    def boards_failed(self) -> int:
        return sum(1 for r in self.results if r.error is not None)

    @property
    def total_jobs(self) -> int:
        return sum(r.jobs_found for r in self.results)

    @property
    def total_internships(self) -> int:
        return sum(r.internships for r in self.results)

    @property
    def total_inserted(self) -> int:
        return sum(r.inserted for r in self.results)

    @property
    def total_updated(self) -> int:
        return sum(r.updated for r in self.results)


def _load_sources() -> None:
    import_module("internhunter.sources.tier_a")
    import_module("internhunter.sources.tier_b")
    import_module("internhunter.sources.tier_c")


def _get_or_create_board(session: Session, source: Source, ref: BoardRef) -> Board:
    board = session.scalar(
        select(Board).where(Board.ats == ref.ats, Board.token == ref.token)
    )
    if board is None:
        board = Board(
            ats=ref.ats,
            token=ref.token,
            company=ref.company,
            tier=str(source.tier),
            board_url=source.board_url(ref),
            tags=(ref.extra or {}).get("tags", []) if ref.extra else [],
        )
        session.add(board)
        session.commit()
    return board


async def poll_boards(
    refs: list[BoardRef], settings: Settings | None = None
) -> PollSummary:
    _load_sources()
    resolved = settings or get_settings()
    init_db(resolved.db_path)
    summary = PollSummary()

    needs_browser = any(
        (source := SOURCE_REGISTRY.get(ref.ats)) is not None and source.needs_browser
        for ref in refs
    )
    if needs_browser and not resolved.enable_browser:
        resolved = resolved.model_copy(update={"enable_browser": True})

    async def fetch(
        ref: BoardRef,
    ) -> tuple[BoardRef, list[NormalizedJob] | None, str | None]:
        source = SOURCE_REGISTRY.get(ref.ats)
        if source is None:
            return ref, None, f"no source registered for ats '{ref.ats}'"
        try:
            jobs = await source.poll(ref, ctx)
        except Exception as exc:
            return ref, None, str(exc)
        return ref, jobs, None

    async with build_fetch_context(resolved) as ctx:
        fetched = await asyncio.gather(*(fetch(ref) for ref in refs))

    all_jobs = [job for _, jobs, _ in fetched if jobs is not None for job in jobs]
    canonical_jobs, summary.duplicates_merged = collapse(all_jobs)
    canonical_uids = {job.job_uid for job in canonical_jobs}

    session = get_session()
    try:
        for ref, jobs, error in fetched:
            source = SOURCE_REGISTRY.get(ref.ats)
            if error is not None or jobs is None or source is None:
                summary.results.append(BoardResult(ref=ref, error=error or "unknown"))
                continue
            board = _get_or_create_board(session, source, ref)
            board_jobs = [job for job in jobs if job.job_uid in canonical_uids]
            inserted, updated = upsert_jobs(session, board_jobs, board)
            board.last_polled = datetime.now(UTC)
            board.last_active = board.last_polled if jobs else board.last_active
            board.total_jobs_seen += len(jobs)
            board.consecutive_failures = 0
            session.commit()
            summary.results.append(
                BoardResult(
                    ref=ref,
                    jobs_found=len(jobs),
                    internships=sum(1 for j in jobs if j.is_internship),
                    inserted=inserted,
                    updated=updated,
                )
            )
        for ref, _jobs, error in fetched:
            if error is None:
                continue
            failed = session.scalar(
                select(Board).where(Board.ats == ref.ats, Board.token == ref.token)
            )
            if failed is not None:
                failed.consecutive_failures += 1
                session.commit()
    finally:
        session.close()

    return summary


def run_poll(
    ats: list[str] | None = None,
    limit: int | None = None,
    settings: Settings | None = None,
) -> PollSummary:
    refs: list[BoardRef] = []
    if ats:
        for value in ats:
            refs.extend(load_boards(ats=value))
    else:
        refs = load_boards()
    if limit is not None:
        refs = refs[:limit]
    return asyncio.run(poll_boards(refs, settings=settings))
