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


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from internhunter.web.app import create_app

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

    async def run() -> list[Detection]:
        async with build_fetch_context() as ctx:
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
            if args.method == "urlscan":
                from internhunter.discovery.urlscan import discover_from_urlscan

                ats = [a.strip() for a in args.ats.split(",") if a.strip()] if args.ats else None
                return await discover_from_urlscan(ctx, ats=ats)
            if args.method == "yc":
                from internhunter.discovery.yc import discover_from_yc

                return await discover_from_yc(ctx, limit=args.limit)
            if args.method == "vc":
                from internhunter.discovery.vc import discover_from_vc

                return await discover_from_vc(ctx, limit=args.limit)
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
    init_db()
    session = get_session()
    try:
        scored = llm_score_jobs(
            session,
            get_backend(settings),
            settings=settings,
            top_k=args.top_k,
            cache=LlmCache(settings.cache_dir),
        )
    finally:
        session.close()
    print(f"llm-scored {scored} jobs")


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

    detect = subparsers.add_parser("detect")
    detect.add_argument("url")

    discover = subparsers.add_parser("discover")
    discover.add_argument(
        "--method",
        choices=["sitemap", "common_crawl", "searxng", "hackernews", "urlscan", "yc", "vc"],
        required=True,
    )
    discover.add_argument("--url", default=None)
    discover.add_argument("--ats", default=None)
    discover.add_argument("--months", type=int, default=6)
    discover.add_argument("--limit", type=int, default=400)

    subparsers.add_parser("score")

    score_llm = subparsers.add_parser("score-llm")
    score_llm.add_argument("--top-k", type=int, default=20)

    notify = subparsers.add_parser("notify")
    notify.add_argument("--channel", choices=["discord", "ntfy", "feed", "all"], default="all")

    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--run-now", action="store_true")
    schedule.add_argument("--ats", default=None)

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
    if args.command == "detect":
        _cmd_detect(args)
        return
    if args.command == "discover":
        _cmd_discover(args)
        return
    if args.command == "score":
        _cmd_score(args)
        return
    if args.command == "score-llm":
        _cmd_score_llm(args)
        return
    if args.command == "notify":
        _cmd_notify(args)
        return
    if args.command == "schedule":
        _cmd_schedule(args)
        return
    parser.print_help()
