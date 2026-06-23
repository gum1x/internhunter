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


@dataclass
class DiscoverySummary:
    boards_new: int = 0
    boards_seen: int = 0
    jobs_ingested: int = 0
    listings_reresolved: int = 0
    per_method: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


async def discover_all(settings: Settings | None = None) -> DiscoverySummary:
    """Run the cheap discovery channels in one pass and grow the board registry.

    This is what the scheduler runs daily so the registry stops being starved between
    manual CLI runs. Each channel fails soft and is reported in ``per_method``.
    """
    from internhunter.discovery.bigco import ingest_bigco
    from internhunter.discovery.common_crawl import discover_from_common_crawl
    from internhunter.discovery.edgar import discover_from_edgar
    from internhunter.discovery.fingerprint import detection_to_board_ref
    from internhunter.discovery.google_jobs import ingest_google_jobs
    from internhunter.discovery.hackernews import discover_from_hackernews
    from internhunter.discovery.indeed import ingest_indeed
    from internhunter.discovery.internship_lists import ingest_internship_lists
    from internhunter.discovery.job_apis import ingest_job_apis
    from internhunter.discovery.linkedin import ingest_linkedin
    from internhunter.discovery.merge import merge_boards
    from internhunter.discovery.reresolve import reresolve_listings
    from internhunter.discovery.similar import discover_similar_companies
    from internhunter.discovery.university import ingest_universities
    from internhunter.discovery.urlscan import discover_from_urlscan
    from internhunter.discovery.usajobs import ingest_usajobs
    from internhunter.discovery.wayback import discover_from_wayback

    resolved = settings or get_settings()
    init_db(resolved.db_path)
    summary = DiscoverySummary()

    async with build_fetch_context(resolved) as ctx:
        detection_channels = {
            "common_crawl": discover_from_common_crawl(ctx),
            "urlscan": discover_from_urlscan(ctx),
            "hackernews": discover_from_hackernews(ctx),
            "wayback": discover_from_wayback(ctx),
            "similar": discover_similar_companies(ctx, resolved),
            "edgar": discover_from_edgar(ctx, resolved),
        }
        results = await asyncio.gather(
            *detection_channels.values(), return_exceptions=True
        )

    all_refs: list[BoardRef] = []
    for name, result in zip(detection_channels, results, strict=True):
        if isinstance(result, BaseException):
            summary.errors.append(f"{name}: {result}")
            summary.per_method[name] = 0
            continue
        refs = [detection_to_board_ref(d) for d in result]
        summary.per_method[name] = len(refs)
        all_refs.extend(refs)

    # Optional GitHub code-search channel (opt-in; no-op without flag + token).
    if resolved.github_code_search and resolved.github_token:
        from internhunter.discovery.github_code import discover_from_github_code

        try:
            async with build_fetch_context(resolved) as ctx:
                detections = await discover_from_github_code(ctx, resolved)
            gh_refs = [detection_to_board_ref(d) for d in detections]
            summary.per_method["github_code"] = len(gh_refs)
            all_refs.extend(gh_refs)
        except Exception as exc:
            summary.errors.append(f"github_code: {exc}")
            summary.per_method["github_code"] = 0

    merged = merge_boards(all_refs)
    summary.boards_new += merged.new_boards
    summary.boards_seen += merged.existing

    # List + API ingestors manage their own context and upsert jobs directly.
    # Keyless (no-login) ingestors. Indeed is keyless too (it only needs a browser to clear the
    # bot-wall) so it runs here; handshake needs a login session and stays out of the daily run.
    for name, coro in (
        ("internship_lists", ingest_internship_lists(resolved)),
        ("job_apis", ingest_job_apis(resolved)),
        ("linkedin", ingest_linkedin(resolved)),
        ("usajobs", ingest_usajobs(resolved)),
        ("bigco", ingest_bigco(resolved)),
        ("university", ingest_universities(resolved)),
        ("google_jobs", ingest_google_jobs(resolved)),
        ("indeed", ingest_indeed(resolved)),
    ):
        try:
            _entries, jobs, new_boards = await coro
            summary.per_method[name] = new_boards
            summary.boards_new += new_boards
            summary.jobs_ingested += jobs
        except Exception as exc:
            summary.errors.append(f"{name}: {exc}")
            summary.per_method[name] = 0

    # Greenhouse global job-ID frontier: walk the recent ID space to ingest brand-new
    # postings and discover never-seen boards in one pass (incremental via checkpoint).
    try:
        from internhunter.discovery.greenhouse_frontier import discover_greenhouse_frontier

        async with build_fetch_context(resolved) as ctx:
            frontier = await discover_greenhouse_frontier(ctx, resolved)
        summary.per_method["greenhouse_frontier"] = len(frontier.new_tokens)
        summary.boards_new += len(frontier.new_tokens)
        summary.jobs_ingested += len(frontier.jobs)
    except Exception as exc:
        summary.errors.append(f"greenhouse_frontier: {exc}")
        summary.per_method["greenhouse_frontier"] = 0

    # Recover real ATS boards from jobs stuck as ats='listing' at ingest.
    try:
        examined, new_boards = await reresolve_listings(resolved)
        summary.listings_reresolved = examined
        summary.per_method["reresolve"] = new_boards
        summary.boards_new += new_boards
    except Exception as exc:
        summary.errors.append(f"reresolve: {exc}")
        summary.per_method["reresolve"] = 0

    return summary


def run_discovery(settings: Settings | None = None) -> DiscoverySummary:
    """Sync wrapper for the CLI and APScheduler."""
    return asyncio.run(discover_all(settings=settings))


def run_score(settings: Settings | None = None) -> int:
    """Embedding fit re-rank of ALL jobs against the (résumé-enhanced) profile. Cheap."""
    from internhunter.match.embed import default_encoder
    from internhunter.match.score import score_jobs

    resolved = settings or get_settings()
    init_db(resolved.db_path)
    session = get_session()
    try:
        return score_jobs(session, default_encoder(), settings=resolved)
    finally:
        session.close()


def run_score_llm(settings: Settings | None = None, top_k: int | None = None) -> int:
    """LLM deep-read of the next batch of unrated internships (skip-aware, so successive
    runs progress through the corpus across Claude usage-limit windows)."""
    from internhunter.llm.client import LlmCache, get_backend
    from internhunter.llm.score import llm_score_jobs

    resolved = settings or get_settings()
    init_db(resolved.db_path)
    session = get_session()
    try:
        return llm_score_jobs(
            session, get_backend(resolved), settings=resolved,
            top_k=top_k if top_k is not None else resolved.llm_rating_top_k,
            cache=LlmCache(resolved.cache_dir),
        )
    finally:
        session.close()
