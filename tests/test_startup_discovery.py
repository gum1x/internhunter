from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.careers import resolve_company_ats
from internhunter.discovery.vc import discover_from_vc
from internhunter.discovery.yc import discover_from_yc


async def test_resolve_company_ats_from_careers_page(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses["https://acme.com"] = httpx.Response(200, text="<html>no board here</html>")
    ctx.responses["https://acme.com/careers"] = httpx.Response(
        200, text='<a href="https://jobs.lever.co/acme">Open roles</a>'
    )
    dets = await resolve_company_ats(ctx, "https://acme.com")
    assert [(d.ats, d.token) for d in dets] == [("lever", "acme")]


async def test_discover_from_yc(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses["https://yc-oss.github.io/api/companies/all.json"] = httpx.Response(
        200,
        text=json.dumps(
            [
                {
                    "name": "Acme",
                    "website": "https://acme.com",
                    "status": "Active",
                    "isHiring": True,
                },
                {"name": "Beta", "website": "https://beta.io", "status": "Active"},
                {"name": "Dead", "website": "https://dead.io", "status": "Inactive"},
                {"name": "NoSite", "status": "Active"},
            ]
        ),
    )
    ctx.responses["https://acme.com"] = httpx.Response(
        200, text='<iframe src="https://boards.greenhouse.io/acme"></iframe>'
    )
    ctx.responses["https://beta.io"] = httpx.Response(
        200, text='<a href="https://jobs.ashbyhq.com/beta">jobs</a>'
    )
    dets = await discover_from_yc(ctx, limit=10)
    keys = {(d.ats, d.token) for d in dets}
    assert ("greenhouse", "acme") in keys
    assert ("ashby", "beta") in keys


async def test_discover_from_vc(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    portfolio = "https://vc.example/portfolio"
    ctx.responses[portfolio] = httpx.Response(
        200,
        text=(
            '<a href="https://portco.com">Portfolio Co</a>'
            '<a href="https://twitter.com/vc">twitter</a>'
            '<a href="https://vc.example/about">about</a>'
        ),
    )
    ctx.responses["https://portco.com"] = httpx.Response(
        200, text='<a href="https://jobs.lever.co/portco">careers</a>'
    )
    dets = await discover_from_vc(ctx, portfolios=(portfolio,))
    assert ("lever", "portco") in {(d.ats, d.token) for d in dets}
