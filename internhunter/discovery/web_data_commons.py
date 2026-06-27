"""Web Data Commons — schema.org ``JobPosting`` extracted in bulk from Common Crawl.

WDC (webdatacommons.org/structureddata) publishes pre-parsed JobPosting microdata as gzipped
N-Quads, so we skip crawling+HTML parsing entirely: stream the dataset, pull apply/posting URLs,
and fingerprint each to recover ATS boards en masse. Multi-GB, so this streams line-by-line and
is **off by default** (set ``web_data_commons_url`` to the verified dataset URL to enable).
"""
from __future__ import annotations

import re
import zlib
from collections.abc import Iterable

from internhunter.config.settings import Settings, get_settings
from internhunter.core.fetch import build_fetch_context
from internhunter.discovery.fingerprint import Detection, detect_from_url, detection_to_board_ref
from internhunter.discovery.merge import merge_boards

# Predicates on a JobPosting whose object carries an apply/posting/company URL.
_JOB_PREDICATE_RE = re.compile(
    r"schema\.org/(?:url|applyUrl|sameAs|hiringOrganization)", re.IGNORECASE
)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def detections_from_nquads(lines: Iterable[str]) -> list[Detection]:
    """Parse N-Quads lines, fingerprinting URLs on JobPosting URL/apply/company predicates."""
    seen: set[tuple[str, str]] = set()
    out: list[Detection] = []
    for line in lines:
        if not _JOB_PREDICATE_RE.search(line):
            continue
        for url in _URL_RE.findall(line):
            det = detect_from_url(url.rstrip(">.,"))
            if det is None:
                continue
            key = (det.ats, det.token)
            if key in seen:
                continue
            seen.add(key)
            out.append(det)
    return out


async def discover_from_web_data_commons(
    ctx: object | None = None, settings: Settings | None = None
) -> list[Detection]:
    resolved = settings or get_settings()
    url = resolved.web_data_commons_url
    if not url:
        return []

    detections: list[Detection] = []
    seen: set[tuple[str, str]] = set()
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)  # gzip stream
    buf = ""
    async with build_fetch_context(resolved) as fctx:
        try:
            async with fctx.client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    raw = decompressor.decompress(chunk) if url.endswith(".gz") else chunk
                    buf += raw.decode("utf-8", "ignore")
                    lines = buf.split("\n")
                    buf = lines.pop()
                    for det in detections_from_nquads(lines):
                        key = (det.ats, det.token)
                        if key in seen:
                            continue
                        seen.add(key)
                        detections.append(det)
        except Exception:
            fctx.logger.debug("web_data_commons stream failed for {}", url)
            return detections
    return detections


async def run_web_data_commons(settings: Settings | None = None) -> int:
    detections = await discover_from_web_data_commons(settings=settings)
    merged = merge_boards([detection_to_board_ref(d) for d in detections])
    return merged.new_boards
