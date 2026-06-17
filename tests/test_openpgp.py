from __future__ import annotations

from urllib.parse import quote

import httpx

from internhunter.contacts.email.openpgp import pgp_email_exists

_BASE = "https://keys.openpgp.org/vks/v1/by-email/"


async def test_pgp_email_exists_true_on_key_body(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    url = _BASE + quote("jane@acme.com")
    ctx.responses[url] = httpx.Response(
        200,
        text="-----BEGIN PGP PUBLIC KEY BLOCK-----\n...\n-----END PGP PUBLIC KEY BLOCK-----",
    )
    assert await pgp_email_exists(ctx, "Jane@Acme.com") is True


async def test_pgp_email_exists_false_on_404(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    assert await pgp_email_exists(ctx, "nobody@acme.com") is False


async def test_pgp_email_exists_false_on_bad_address(fake_fetch_context) -> None:  # type: ignore[no-untyped-def]
    ctx = fake_fetch_context
    assert await pgp_email_exists(ctx, "not-an-email") is False
