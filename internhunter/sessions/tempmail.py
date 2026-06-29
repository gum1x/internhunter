"""Disposable inbox via mail.tm's free public API (keyless, no signup)."""
from __future__ import annotations

import asyncio
import random
import re
import string
from dataclasses import dataclass
from typing import Any

import httpx

_API = "https://api.mail.tm"
_CODE_RE = re.compile(r"\b(\d{4,8})\b")


@dataclass
class Inbox:
    address: str
    password: str
    token: str


async def _api(
    client: httpx.AsyncClient, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    url = f"{_API}{path}"
    return await client.request(method, url, **kwargs)


async def create_inbox() -> Inbox:
    async with httpx.AsyncClient(timeout=30.0) as client:
        domains_resp = await _api(client, "GET", "/domains")
        domains_resp.raise_for_status()
        domains = domains_resp.json()
        domain = domains["hydra:member"][0]["domain"]
        local = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        address = f"{local}@{domain}"
        password = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        create_resp = await _api(
            client,
            "POST",
            "/accounts",
            json={"address": address, "password": password},
        )
        create_resp.raise_for_status()
        token_resp = await _api(
            client,
            "POST",
            "/token",
            json={"address": address, "password": password},
        )
        token_resp.raise_for_status()
        token = token_resp.json()["token"]
        return Inbox(address=address, password=password, token=token)


async def wait_for_email(
    inbox: Inbox,
    *,
    subject_contains: str | None = None,
    timeout: float = 120.0,
    poll_interval: float = 3.0,
) -> str | None:
    headers = {"Authorization": f"Bearer {inbox.token}"}
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=30.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            resp = await _api(client, "GET", "/messages", headers=headers)
            if resp.status_code == 200:
                messages = resp.json().get("hydra:member", [])
                for msg in messages:
                    subject = str(msg.get("subject", ""))
                    if subject_contains and subject_contains.lower() not in subject.lower():
                        continue
                    msg_id = msg.get("id")
                    if not msg_id:
                        continue
                    detail = await _api(client, "GET", f"/messages/{msg_id}", headers=headers)
                    if detail.status_code == 200:
                        body = detail.json().get("text", "") or detail.json().get("html", "")
                        return str(body)
            await asyncio.sleep(poll_interval)
    return None


def extract_code(body: str) -> str | None:
    match = _CODE_RE.search(body)
    return match.group(1) if match else None