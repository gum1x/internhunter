from __future__ import annotations

from typing import Any

import httpx

from internhunter.core.db import Job


def _fields(job: Job) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if job.company:
        fields.append({"name": "Company", "value": job.company, "inline": True})
    if job.location_normalized:
        fields.append({"name": "Location", "value": job.location_normalized, "inline": True})
    if job.deadline_at is not None:
        fields.append(
            {"name": "Deadline", "value": job.deadline_at.isoformat(), "inline": True}
        )
    return fields


def build_discord_payload(jobs: list[Job]) -> dict[str, Any]:
    embeds: list[dict[str, Any]] = []
    for job in jobs:
        embeds.append(
            {
                "title": job.title,
                "url": job.canonical_url,
                "fields": _fields(job),
            }
        )
    return {
        "content": f"{len(jobs)} new internship match(es)",
        "embeds": embeds,
    }


def send_discord(payload: dict[str, Any], webhook_url: str) -> int:
    response = httpx.post(webhook_url, json=payload)
    return response.status_code
