from __future__ import annotations

import asyncio

from loguru import logger

from internhunter.config.settings import Settings, get_settings
from internhunter.sessions.signup import ensure_handshake_session, ensure_linkedin_session
from internhunter.sessions.store import load_storage_state


async def refresh_sessions(settings: Settings | None = None) -> dict[str, bool]:
    resolved = settings or get_settings()
    results: dict[str, bool] = {}
    if resolved.enable_linkedin_auth:
        if load_storage_state(resolved, "linkedin") is None:
            results["linkedin"] = await ensure_linkedin_session(resolved)
        else:
            results["linkedin"] = True
    if resolved.enable_handshake_auto:
        results["handshake"] = await ensure_handshake_session(resolved)
    return results


def run_refresh_sessions(settings: Settings | None = None) -> dict[str, bool]:
    resolved = settings or get_settings()
    try:
        return asyncio.run(refresh_sessions(resolved))
    except Exception as exc:
        logger.warning("session refresh failed: {}", exc)
        return {}