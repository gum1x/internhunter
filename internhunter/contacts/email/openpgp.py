from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from internhunter.core.fetch import FetchContext

# keys.openpgp.org is a keyless, verifying keyserver: an address only appears in its
# by-email index after the owner clicked a confirmation link sent to that mailbox. So a
# 200 from the by-email endpoint is strong proof the mailbox is real and owner-controlled
# — a free HTTPS signal that sidesteps the blocked port 25. (It's biased toward technical
# users, like the GitHub-commit signal, but a hit is high-confidence.)

_BY_EMAIL = "https://keys.openpgp.org/vks/v1/by-email/"


async def pgp_email_exists(ctx: FetchContext, email: str) -> bool:
    """True if keys.openpgp.org has a verified key for this address.

    The endpoint returns 200 with an ASCII-armored key body when the address has a
    confirmed key, and 404 otherwise. Returns False on any failure."""
    normalized = email.strip().lower()
    if "@" not in normalized:
        return False
    try:
        body = await ctx.get_text(
            f"{_BY_EMAIL}{quote(normalized)}", respect_robots=False
        )
    except Exception:
        return False
    return "BEGIN PGP PUBLIC KEY BLOCK" in body


# NOTE: pgp_emails_for_name is intentionally NOT implemented. keys.openpgp.org
# deliberately offers no name/substring search — its VKS API exposes lookups only by
# exact email, fingerprint, or key-id (by-email / by-fingerprint / by-keyid), precisely
# to prevent address harvesting. There is no keyless endpoint that maps a person's name
# to candidate emails, so a name-search helper cannot be built against this service
# without an API key or scraping a third party. Use pgp_email_exists to confirm
# already-guessed addresses instead.
