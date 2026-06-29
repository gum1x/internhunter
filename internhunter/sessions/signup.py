from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from internhunter.config.settings import Settings, get_settings
from internhunter.sessions.store import save_storage_state
from internhunter.sessions.tempmail import create_inbox, extract_code, wait_for_email


@dataclass
class EduCredential:
    email: str
    password: str


def parse_edu_pool(settings: Settings) -> list[EduCredential]:
    creds: list[EduCredential] = []
    for entry in (settings.handshake_edu_pool or "").split(","):
        entry = entry.strip()
        if not entry or "@" not in entry:
            continue
        if ":" in entry:
            user, password = entry.split(":", 1)
            creds.append(EduCredential(email=user.strip(), password=password.strip()))
        else:
            creds.append(EduCredential(email=entry, password=""))
    return creds


async def ensure_linkedin_session(settings: Settings | None = None) -> bool:
    """Create a LinkedIn session via temp-email signup when none exists."""
    resolved = settings or get_settings()
    from internhunter.sessions.store import load_storage_state

    if load_storage_state(resolved, "linkedin") is not None:
        return True
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("linkedin signup: playwright not installed")
        return False

    inbox = await create_inbox()
    for attempt in range(resolved.session_signup_max_attempts):
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=resolved.browser_headless)
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(
                    "https://www.linkedin.com/signup",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await page.fill('input[name="email-address"]', inbox.address)
                await page.fill('input[name="password"]', inbox.password)
                await page.click('button[type="submit"]')
                body = await wait_for_email(inbox, subject_contains="LinkedIn", timeout=90.0)
                code = extract_code(body or "")
                if code:
                    code_input = page.locator('input[name="pin"]').first
                    if await code_input.count():
                        await code_input.fill(code)
                        await page.click('button[type="submit"]')
                state = await context.storage_state()
                save_storage_state(resolved, "linkedin", state)
                await browser.close()
                logger.info("linkedin session created for {}", inbox.address)
                return True
        except Exception as exc:
            logger.debug("linkedin signup attempt {} failed: {}", attempt + 1, exc)
    return False


async def ensure_handshake_session(settings: Settings | None = None) -> bool:
    """Log into Handshake using edu pool credentials and save storage state."""
    resolved = settings or get_settings()
    from internhunter.sessions.store import resolve_handshake_session

    if resolve_handshake_session(resolved) is not None:
        return True
    creds = parse_edu_pool(resolved)
    if not creds:
        logger.info("handshake: no edu pool configured — skipping auto-login")
        return False
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("handshake signup: playwright not installed")
        return False

    cred = creds[0]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=resolved.browser_headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(
                "https://app.joinhandshake.com/login",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            await page.fill('input[type="email"], input[name="email"]', cred.email)
            if cred.password:
                await page.fill('input[type="password"]', cred.password)
                await page.click('button[type="submit"]')
            await page.wait_for_timeout(5000)
            state = await context.storage_state()
            path = save_storage_state(resolved, "handshake", state)
            path.write_text(json.dumps(state), encoding="utf-8")
            resolved.handshake_session.parent.mkdir(parents=True, exist_ok=True)
            resolved.handshake_session.write_text(json.dumps(state), encoding="utf-8")
            logger.info("handshake session saved from edu pool")
            await browser.close()
            return True
        except Exception as exc:
            logger.debug("handshake auto-login failed: {}", exc)
            await browser.close()
            return False