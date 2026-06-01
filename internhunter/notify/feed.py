from __future__ import annotations

import pathlib
from email.utils import format_datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from internhunter.core.db import Job


def _item(channel: Element, job: Job) -> None:
    item = SubElement(channel, "item")
    SubElement(item, "title").text = job.title
    SubElement(item, "link").text = job.canonical_url
    company = job.company or "unknown"
    SubElement(item, "description").text = f"{job.title} at {company}"
    SubElement(item, "guid").text = job.canonical_url
    if job.posted_at is not None:
        SubElement(item, "pubDate").text = format_datetime(job.posted_at)


def build_feed(jobs: list[Job]) -> str:
    rss = Element("rss", attrib={"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "InternHunter"
    SubElement(channel, "link").text = "https://internhunter.local"
    SubElement(channel, "description").text = "New internship matches"
    for job in jobs:
        _item(channel, job)
    return tostring(rss, encoding="unicode", xml_declaration=True)


def write_feed(jobs: list[Job], path: pathlib.Path) -> None:
    path.write_text(build_feed(jobs), encoding="utf-8")
