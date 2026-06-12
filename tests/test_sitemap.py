from __future__ import annotations

from typing import Any

import httpx
import pytest

from internhunter.discovery.sitemap import discover_from_sitemap


@pytest.mark.asyncio
async def test_sitemap_urlset_finds_boards(fake_fetch_context: Any) -> None:
    root = "https://acme.example.com/careers"
    fake_fetch_context.responses["https://acme.example.com/robots.txt"] = httpx.Response(
        200, text="User-agent: *\nSitemap: https://acme.example.com/sitemap.xml\n"
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://boards.greenhouse.io/acme/jobs/1</loc></url>"
        "<url><loc>https://jobs.lever.co/acme</loc></url>"
        "<url><loc>https://acme.example.com/about</loc></url>"
        "<url><loc>https://acme.example.com/blog/post</loc></url>"
        "</urlset>"
    )
    fake_fetch_context.responses["https://acme.example.com/sitemap.xml"] = httpx.Response(
        200, text=sitemap
    )
    fake_fetch_context.responses[root] = httpx.Response(200, text="<html></html>")

    detections = await discover_from_sitemap(root, fake_fetch_context)
    keys = {(d.ats, d.token) for d in detections}

    assert ("greenhouse", "acme") in keys
    assert ("lever", "acme") in keys
    assert len(detections) == len(keys)


@pytest.mark.asyncio
async def test_sitemap_index_recurses(fake_fetch_context: Any) -> None:
    root = "https://acme.example.com/careers"
    fake_fetch_context.responses["https://acme.example.com/robots.txt"] = httpx.Response(
        200, text="Sitemap: https://acme.example.com/sitemap_index.xml\n"
    )
    index = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://acme.example.com/child.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    child = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://jobs.ashbyhq.com/acme</loc></url>"
        "</urlset>"
    )
    fake_fetch_context.responses[
        "https://acme.example.com/sitemap_index.xml"
    ] = httpx.Response(200, text=index)
    fake_fetch_context.responses["https://acme.example.com/child.xml"] = httpx.Response(
        200, text=child
    )
    fake_fetch_context.responses[root] = httpx.Response(200, text="<html></html>")

    detections = await discover_from_sitemap(root, fake_fetch_context)
    keys = {(d.ats, d.token) for d in detections}

    assert ("ashby", "acme") in keys


@pytest.mark.asyncio
async def test_root_html_iframe_without_sitemap(fake_fetch_context: Any) -> None:
    root = "https://acme.example.com/careers"
    html = (
        "<html><body>"
        '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme">'
        "</iframe></body></html>"
    )
    fake_fetch_context.responses[root] = httpx.Response(200, text=html)

    detections = await discover_from_sitemap(root, fake_fetch_context)
    keys = {(d.ats, d.token) for d in detections}

    assert ("greenhouse", "acme") in keys
