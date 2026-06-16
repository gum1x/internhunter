from __future__ import annotations

import httpx

from internhunter.contacts.email.harvest import (
    harvest_commit_patch_email,
    harvest_github_login_email,
    harvest_security_txt,
)


async def test_harvest_security_txt_well_known(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    ctx.responses["https://acme.com/.well-known/security.txt"] = httpx.Response(
        200,
        text="Contact: mailto:security@acme.com\nContact: https://acme.com/report\n",
    )
    emails = await harvest_security_txt(ctx, "acme.com")
    assert emails == ["security@acme.com"]


async def test_harvest_security_txt_legacy_path(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    ctx.responses["https://acme.com/security.txt"] = httpx.Response(
        200, text="Contact: psirt@acme.com\n"
    )
    emails = await harvest_security_txt(ctx, "acme.com")
    assert emails == ["psirt@acme.com"]


async def test_harvest_security_txt_filters_offdomain(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    ctx.responses["https://acme.com/.well-known/security.txt"] = httpx.Response(
        200, text="Contact: mailto:abuse@other.com\n"
    )
    assert await harvest_security_txt(ctx, "acme.com") == []


async def test_harvest_security_txt_empty_on_missing(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    assert await harvest_security_txt(fake_fetch_context, "acme.com") == []


async def test_harvest_commit_patch_email_pulls_from_header(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    url = "https://github.com/acme/repo/commit/abc123"
    ctx.responses[url + ".patch"] = httpx.Response(
        200,
        text="From abc123 Mon Sep 17 00:00:00 2001\n"
        "From: Jane Doe <jane.doe@acme.com>\n"
        "Subject: [PATCH] fix\n",
    )
    assert await harvest_commit_patch_email(ctx, url, "acme.com") == "jane.doe@acme.com"


async def test_harvest_commit_patch_email_skips_noreply(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    url = "https://github.com/acme/repo/commit/def456"
    ctx.responses[url + ".patch"] = httpx.Response(
        200, text="From: Bot <1+bot@users.noreply.github.com>\n"
    )
    assert await harvest_commit_patch_email(ctx, url) is None


async def test_harvest_github_login_email_walks_events(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    ctx.responses["https://api.github.com/users/jdoe/events/public"] = httpx.Response(
        200,
        json=[
            {
                "type": "PushEvent",
                "repo": {"name": "acme/repo"},
                "payload": {"commits": [{"sha": "deadbeef"}]},
            }
        ],
    )
    ctx.responses["https://github.com/acme/repo/commit/deadbeef.patch"] = httpx.Response(
        200, text="From: Jane Doe <jane.doe@acme.com>\n"
    )
    got = await harvest_github_login_email(ctx, "jdoe", "acme.com")
    assert got == "jane.doe@acme.com"
