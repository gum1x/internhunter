from __future__ import annotations

import httpx

from internhunter.core.db import Job


def _line(job: Job) -> str:
    company = job.company or "unknown"
    return f"{job.title} @ {company} — {job.canonical_url}"


def build_ntfy_message(jobs: list[Job]) -> str:
    header = f"{len(jobs)} new internship match(es)"
    lines = [_line(job) for job in jobs]
    return "\n".join([header, *lines])


def send_ntfy(message: str, topic_url: str) -> int:
    response = httpx.post(topic_url, content=message.encode())
    return response.status_code
