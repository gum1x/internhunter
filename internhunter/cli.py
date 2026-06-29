from __future__ import annotations

import argparse

from internhunter.core.db import init_db


def _cmd_poll(args: argparse.Namespace) -> None:
    import asyncio

    from internhunter.core.runner import poll_boards, run_poll
    from internhunter.sources.base import BoardRef

    if args.board:
        if not args.ats:
            raise SystemExit("--ats is required with --board")
        extra = {"dc": args.dc} if args.dc else None
        ref = BoardRef(ats=args.ats.strip(), token=args.board, extra=extra)
        summary = asyncio.run(poll_boards([ref]))
    else:
        ats = [a.strip() for a in args.ats.split(",") if a.strip()] if args.ats else None
        summary = run_poll(ats=ats, limit=args.limit)
    print(
        f"polled {summary.boards_polled} boards "
        f"({summary.boards_failed} failed): "
        f"{summary.total_jobs} jobs, {summary.total_internships} internships, "
        f"{summary.total_inserted} new, {summary.total_updated} updated, "
        f"{summary.duplicates_merged} duplicates merged"
    )
    for result in summary.results:
        if result.error is not None:
            print(f"  ! {result.ref.ats}/{result.ref.token}: {result.error}")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from internhunter.config.settings import get_settings
    from internhunter.web.app import create_app

    settings = get_settings()
    if args.host not in _LOOPBACK_HOSTS and not (settings.auth_user and settings.auth_pass):
        raise SystemExit(
            f"refusing to bind non-loopback host {args.host!r} without auth: set "
            "INTERNHUNTER_AUTH_USER and INTERNHUNTER_AUTH_PASS, or bind 127.0.0.1"
        )

    uvicorn.run(create_app(), host=args.host, port=args.port)


def _cmd_detect(args: argparse.Namespace) -> None:
    from internhunter.discovery.fingerprint import detect_from_url

    detection = detect_from_url(args.url)
    if detection is None:
        print("no ATS board detected")
        return
    print(f"{detection.ats}\t{detection.token}")


def _cmd_discover(args: argparse.Namespace) -> None:
    import asyncio

    from internhunter.core.fetch import build_fetch_context
    from internhunter.discovery.fingerprint import Detection, detection_to_board_ref
    from internhunter.discovery.merge import merge_boards

    if args.method == "greenhouse_frontier":
        from internhunter.discovery.greenhouse_frontier import run_greenhouse_frontier

        # window unset -> None -> the crawler uses settings.greenhouse_frontier_window (1500).
        frontier = run_greenhouse_frontier(window=args.limit)
        print(
            f"greenhouse frontier: probed {frontier.probed} ids, "
            f"resolved {frontier.resolved} jobs, "
            f"{len(frontier.new_tokens)} new boards, high-water {frontier.high_water}"
        )
        for token in sorted(frontier.new_tokens):
            print(f"  + greenhouse/{token}")
        return

    async def run() -> list[Detection]:
        from internhunter.config.settings import get_settings

        settings = get_settings()
        if args.method == "vc" and not settings.enable_browser:
            settings = settings.model_copy(update={"enable_browser": True})
        async with build_fetch_context(settings) as ctx:
            if args.method == "sitemap":
                from internhunter.discovery.sitemap import discover_from_sitemap

                if not args.url:
                    raise SystemExit("--url is required for --method sitemap")
                return await discover_from_sitemap(args.url, ctx)
            if args.method == "searxng":
                from internhunter.discovery.searxng import discover_from_searxng

                if not args.url:
                    raise SystemExit("--url (SearXNG base) is required for --method searxng")
                return await discover_from_searxng(ctx, args.url)
            if args.method == "hackernews":
                from internhunter.discovery.hackernews import discover_from_hackernews

                return await discover_from_hackernews(ctx, months=args.months)
            if args.method == "crtsh":
                from internhunter.discovery.crt_sh import discover_from_crtsh

                if not args.url:
                    raise SystemExit("--url (company domain) is required for --method crtsh")
                return await discover_from_crtsh(ctx, args.url)
            if args.method == "jsonld":
                from internhunter.discovery.jsonld import discover_from_jsonld

                if not args.url:
                    raise SystemExit("--url (careers page) is required for --method jsonld")
                return await discover_from_jsonld(ctx, args.url)
            if args.method == "crt_bulk":
                from internhunter.discovery.crt_bulk import discover_from_crt_bulk

                return await discover_from_crt_bulk(ctx)
            if args.method == "board_resolve":
                from internhunter.discovery.board_resolve import discover_from_board_resolve

                return await discover_from_board_resolve(ctx, settings)
            if args.method == "web_data_commons":
                from internhunter.discovery.web_data_commons import (
                    discover_from_web_data_commons,
                )

                return await discover_from_web_data_commons(ctx, settings)
            if args.method == "wayback":
                from internhunter.discovery.wayback import discover_from_wayback

                return await discover_from_wayback(ctx)
            if args.method == "similar":
                from internhunter.discovery.similar import discover_similar_companies

                return await discover_similar_companies(ctx, settings)
            if args.method == "edgar":
                from internhunter.discovery.edgar import discover_from_edgar

                return await discover_from_edgar(ctx, settings)
            if args.method == "urlscan":
                from internhunter.discovery.urlscan import discover_from_urlscan

                ats = [a.strip() for a in args.ats.split(",") if a.strip()] if args.ats else None
                return await discover_from_urlscan(ctx, ats=ats)
            if args.method == "github_code":
                from internhunter.discovery.github_code import discover_from_github_code

                ats = [a.strip() for a in args.ats.split(",") if a.strip()] if args.ats else None
                return await discover_from_github_code(ctx, settings, ats=ats)
            if args.method == "yc":
                from internhunter.discovery.yc import discover_from_yc

                return await discover_from_yc(ctx, limit=args.limit or 400)
            if args.method == "vc":
                from internhunter.discovery.vc import discover_from_vc

                return await discover_from_vc(ctx, limit=args.limit or 400)
            from internhunter.discovery.common_crawl import discover_from_common_crawl

            ats = [a.strip() for a in args.ats.split(",") if a.strip()] if args.ats else None
            return await discover_from_common_crawl(ctx, ats=ats)

    detections = asyncio.run(run())
    refs = [detection_to_board_ref(d) for d in detections]
    result = merge_boards(refs)
    print(
        f"discovered {result.discovered} boards: "
        f"{result.new_boards} new, {result.existing} already known"
    )
    for ref in result.new_refs:
        print(f"  + {ref.ats}/{ref.token}")


def _cmd_discover_all(args: argparse.Namespace) -> None:
    from internhunter.core.runner import run_discovery

    summary = run_discovery()
    print(
        f"discovery: {summary.boards_new} new boards, "
        f"{summary.boards_seen} already known, {summary.jobs_ingested} jobs ingested"
    )
    for method, count in summary.per_method.items():
        print(f"  {method:18} {count}")
    for error in summary.errors[:10]:
        print(f"  ! {error}")


def _cmd_reresolve(args: argparse.Namespace) -> None:
    import asyncio

    from internhunter.discovery.reresolve import reresolve_listings

    examined, new_boards = asyncio.run(reresolve_listings(limit=args.limit or 200))
    print(f"reresolved {examined} listing jobs: {new_boards} new boards")


def _cmd_score(args: argparse.Namespace) -> None:
    from internhunter.core.db import get_session, init_db
    from internhunter.match.embed import default_encoder
    from internhunter.match.score import score_jobs

    init_db()
    session = get_session()
    try:
        scored = score_jobs(session, default_encoder())
    finally:
        session.close()
    print(f"scored {scored} jobs")


def _cmd_score_llm(args: argparse.Namespace) -> None:
    from internhunter.config.settings import get_settings
    from internhunter.core.db import get_session, init_db
    from internhunter.llm.client import LlmCache, get_backend
    from internhunter.llm.score import llm_score_jobs

    settings = get_settings()
    top_k = settings.llm_rating_top_k if args.top_k is None else args.top_k
    init_db()
    session = get_session()
    try:
        scored = llm_score_jobs(
            session,
            get_backend(settings),
            settings=settings,
            top_k=top_k,
            cache=LlmCache(settings.cache_dir),
        )
    finally:
        session.close()
    print(f"llm-scored {scored} jobs")


def _cmd_score_quality(args: argparse.Namespace) -> None:
    from internhunter.config.settings import get_settings
    from internhunter.core.db import get_session, init_db
    from internhunter.llm.client import LlmCache, get_backend
    from internhunter.llm.quality import judge_quality_jobs

    settings = get_settings()
    init_db()
    session = get_session()
    try:
        judged = judge_quality_jobs(
            session,
            get_backend(settings),
            settings=settings,
            top_k=args.top_k,
            cache=LlmCache(settings.cache_dir),
        )
    finally:
        session.close()
    print(f"quality-judged {judged} borderline jobs")


def _cmd_find_contacts(args: argparse.Namespace) -> None:
    from internhunter.config.settings import get_settings
    from internhunter.contacts.runner import run_find_contacts
    from internhunter.contacts.selfcheck import format_status

    settings = get_settings()
    if args.methods:
        settings = settings.model_copy(update={"contacts_methods": args.methods})
    if args.verify:
        settings = settings.model_copy(update={"verify_emails": True})
    print(format_status(settings))
    summary = run_find_contacts(
        limit=args.limit, only_slug=args.company, settings=settings
    )
    print(
        f"enriched {summary.companies} companies: "
        f"{summary.people_found} contacts "
        f"({summary.emails_found} with email), "
        f"{summary.contacts_inserted} new, {summary.contacts_updated} updated"
    )
    for error in summary.errors[:10]:
        print(f"  ! {error}")


def _cmd_notify(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from internhunter.config.settings import get_settings
    from internhunter.core.db import Job, get_session, init_db
    from internhunter.notify.discord import build_discord_payload, send_discord
    from internhunter.notify.feed import write_feed
    from internhunter.notify.ntfy import build_ntfy_message, send_ntfy
    from internhunter.notify.select import select_notifiable

    settings = get_settings()
    init_db()
    session = get_session()
    try:
        jobs = list(session.scalars(select(Job).where(Job.is_internship.is_(True))))
    finally:
        session.close()
    selected = select_notifiable(jobs, min_fit=settings.notify_min_fit)
    print(f"{len(selected)} notifiable roles")
    if not selected:
        return
    if args.channel in ("discord", "all") and settings.discord_webhook_url:
        status = send_discord(build_discord_payload(selected), settings.discord_webhook_url)
        print(f"  discord -> {status}")
    if args.channel in ("ntfy", "all") and settings.ntfy_topic_url:
        status = send_ntfy(build_ntfy_message(selected), settings.ntfy_topic_url)
        print(f"  ntfy -> {status}")
    if args.channel in ("feed", "all"):
        write_feed(selected, settings.feed_path)
        print(f"  feed -> {settings.feed_path}")


def _cmd_schedule(args: argparse.Namespace) -> None:
    import time

    from internhunter.config.settings import get_settings
    from internhunter.scheduler import build_scheduler, run_now

    settings = get_settings()
    if args.run_now:
        run_now(ats=args.ats, settings=settings)
        return
    scheduler = build_scheduler(settings)
    scheduler.start()
    print("scheduler started; press Ctrl-C to stop")
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def _listing_ingestors() -> dict[str, tuple[str, str, str]]:
    """name -> (label, module, function). Keyless ones join `--source all`; indeed/handshake
    are explicit-only (browser/auth), like oflc/perm."""
    return {
        "github": ("github lists", "internhunter.discovery.internship_lists",
                   "ingest_internship_lists"),
        "apis": ("job apis", "internhunter.discovery.job_apis", "ingest_job_apis"),
        "linkedin": ("linkedin", "internhunter.discovery.linkedin", "ingest_linkedin"),
        "usajobs": ("usajobs", "internhunter.discovery.usajobs", "ingest_usajobs"),
        "bigco": ("big-company", "internhunter.discovery.bigco", "ingest_bigco"),
        "university": ("university portals", "internhunter.discovery.university",
                       "ingest_universities"),
        "google_jobs": ("google jobs", "internhunter.discovery.google_jobs",
                        "ingest_google_jobs"),
        "indeed": ("indeed", "internhunter.discovery.indeed", "ingest_indeed"),
        "handshake": ("handshake", "internhunter.discovery.handshake", "ingest_handshake"),
        "bluesky": ("bluesky", "internhunter.discovery.bluesky", "ingest_bluesky"),
        "reddit": ("reddit", "internhunter.discovery.reddit", "ingest_reddit"),
        "eures": ("eures", "internhunter.discovery.eures", "ingest_eures"),
        "arbeitsagentur": ("arbeitsagentur (DE)", "internhunter.discovery.arbeitsagentur",
                           "ingest_arbeitsagentur"),
        "idealist": ("idealist", "internhunter.discovery.idealist", "ingest_idealist"),
    }


# In `--source all`: every keyless (no-login) ingestor, including Indeed (keyless, but spins up
# a browser to clear the bot-wall). Only handshake stays explicit-only — it requires a saved
# university login session and is inert without one.
_ALL_LISTING_SOURCES = ("github", "apis", "linkedin", "usajobs", "bigco", "university",
                        "google_jobs", "indeed", "bluesky", "reddit", "eures",
                        "arbeitsagentur", "idealist")


def _cmd_ingest(args: argparse.Namespace) -> None:
    import asyncio
    from importlib import import_module

    total_entries = total_jobs = total_boards = 0
    ingestors = _listing_ingestors()
    selected = (
        _ALL_LISTING_SOURCES if args.source == "all"
        else (args.source,) if args.source in ingestors
        else ()
    )
    for name in selected:
        label, module, func = ingestors[name]
        coro = getattr(import_module(module), func)()
        entries, jobs, boards = asyncio.run(coro)
        print(f"  {label}: {entries} entries -> {jobs} jobs, {boards} new boards")
        total_entries += entries
        total_jobs += jobs
        total_boards += boards
    # SBIR is keyless so it joins "all"; oflc/perm need a --url, so they stay explicit-only.
    disclosure_sources = [s for s in ("oflc", "perm", "sbir") if s == args.source]
    if args.source == "all":
        disclosure_sources = ["sbir"]
    disclosure_rows = disclosure_leads = disclosure_companies = 0
    for src in disclosure_sources:
        from internhunter.discovery.disclosure import run_ingest_disclosure

        summary = run_ingest_disclosure(src, url=args.url)
        print(
            f"  {src}: {summary.rows} rows -> {summary.leads} new leads, "
            f"{summary.companies} companies signaled"
        )
        for error in summary.errors[:5]:
            print(f"  ! {error}")
        disclosure_rows += summary.rows
        disclosure_leads += summary.leads
        disclosure_companies += summary.companies

    print(
        f"ingested {total_entries} entries -> "
        f"{total_jobs} jobs upserted, {total_boards} new boards added"
    )
    if disclosure_rows:
        print(
            f"disclosure: {disclosure_rows} rows -> {disclosure_leads} leads, "
            f"{disclosure_companies} companies signaled"
        )


def _cmd_registry(args: argparse.Namespace) -> None:
    from internhunter.registry import registry_stats

    stats = registry_stats()
    total = stats.pop("total", 0)
    for ats in sorted(stats):
        print(f"  {ats:16} {stats[ats]}")
    print(f"  {'total':16} {total}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="internhunter")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init-db")

    poll = subparsers.add_parser("poll")
    poll.add_argument("--ats", default=None)
    poll.add_argument("--limit", type=int, default=None)
    poll.add_argument("--board", default=None)
    poll.add_argument("--dc", default=None)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    registry = subparsers.add_parser("registry")
    registry.add_argument("action", choices=["stats"])

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument(
        "--source",
        choices=[
            "github", "apis", "linkedin", "usajobs", "bigco", "university", "google_jobs",
            "indeed", "handshake", "bluesky", "reddit", "eures", "arbeitsagentur", "idealist",
            "oflc", "perm", "sbir", "all",
        ],
        default="all",
    )
    ingest.add_argument(
        "--url", default=None, help="OFLC LCA/PERM .xlsx URL or local path (oflc/perm sources)"
    )

    detect = subparsers.add_parser("detect")
    detect.add_argument("url")

    discover = subparsers.add_parser("discover")
    discover.add_argument(
        "--method",
        choices=[
            "sitemap", "common_crawl", "searxng", "hackernews", "urlscan",
            "yc", "vc", "crtsh", "jsonld", "wayback", "similar", "edgar",
            "github_code", "greenhouse_frontier",
            "crt_bulk", "board_resolve", "web_data_commons",
        ],
        required=True,
    )
    discover.add_argument("--url", default=None)
    discover.add_argument("--ats", default=None)
    discover.add_argument("--months", type=int, default=6)
    # Unset by default: yc/vc fall back to 400; greenhouse_frontier falls back to the
    # configured window (1500). An explicit --limit N overrides for the chosen method.
    discover.add_argument("--limit", type=int, default=None)

    subparsers.add_parser("discover-all")
    reresolve = subparsers.add_parser("reresolve")
    reresolve.add_argument("--limit", type=int, default=200)

    subparsers.add_parser("score")

    score_llm = subparsers.add_parser("score-llm")
    score_llm.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="max jobs to rate (0 or omit with INTERNHUNTER_LLM_RATING_TOP_K=0 = all unrated)",
    )

    score_quality = subparsers.add_parser("score-quality")
    score_quality.add_argument("--top-k", type=int, default=None)

    find_contacts = subparsers.add_parser("find-contacts")
    find_contacts.add_argument("--limit", type=int, default=50)
    find_contacts.add_argument("--company", default=None, help="single company_slug")
    find_contacts.add_argument(
        "--methods",
        default=None,
        help=("comma list: searxng,github,git_commits,gitlab_commits,team,staffspy,"
              "ats_raw,registries,gov_disclosure"),
    )
    find_contacts.add_argument("--verify", action="store_true", help="run holehe verification")

    notify = subparsers.add_parser("notify")
    notify.add_argument("--channel", choices=["discord", "ntfy", "feed", "all"], default="all")

    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--run-now", action="store_true")
    schedule.add_argument("--ats", default=None)

    subparsers.add_parser("mcp", help="run the MCP server (stdio) for Claude/MCP clients")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
        return
    if args.command == "poll":
        _cmd_poll(args)
        return
    if args.command == "serve":
        _cmd_serve(args)
        return
    if args.command == "registry":
        _cmd_registry(args)
        return
    if args.command == "ingest":
        _cmd_ingest(args)
        return
    if args.command == "detect":
        _cmd_detect(args)
        return
    if args.command == "discover":
        _cmd_discover(args)
        return
    if args.command == "discover-all":
        _cmd_discover_all(args)
        return
    if args.command == "reresolve":
        _cmd_reresolve(args)
        return
    if args.command == "score":
        _cmd_score(args)
        return
    if args.command == "score-llm":
        _cmd_score_llm(args)
        return
    if args.command == "score-quality":
        _cmd_score_quality(args)
        return
    if args.command == "find-contacts":
        _cmd_find_contacts(args)
        return
    if args.command == "notify":
        _cmd_notify(args)
        return
    if args.command == "schedule":
        _cmd_schedule(args)
        return
    if args.command == "mcp":
        from internhunter.mcp_server import main as mcp_main

        mcp_main()
        return
    parser.print_help()
