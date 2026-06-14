from __future__ import annotations

# Per-mailbox existence check over HTTPS for Microsoft 365 domains — the RCPT-equivalent
# the blocked port 25 denies us. Microsoft's GetCredentialType returns whether an account
# exists; we cross-check Autodiscover before calling it confirmed. No SMTP, no RBL risk.

_GCT = "https://login.microsoftonline.com/common/GetCredentialType"
_AUTODISCOVER = "https://outlook.office365.com/autodiscover/autodiscover.json/v1.0/{email}"


async def _autodiscover_ok(email: str, timeout: float) -> bool | None:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.get(
                _AUTODISCOVER.format(email=email), params={"Protocol": "Autodiscoverv1"}
            )
        if resp.status_code == 200:
            return True
        if resp.status_code in (302, 404):
            return False
        return None
    except Exception:
        return None


async def m365_confirms(email: str, timeout: float = 15.0) -> bool | None:
    """True = mailbox exists, False = does not, None = unknown (throttled/federated/error).

    Requires GetCredentialType AND Autodiscover to agree before returning True.
    """
    try:
        import httpx
    except Exception:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_GCT, json={"Username": email})
        data = resp.json()
    except Exception:
        return None

    if data.get("ThrottleStatus") == 2:
        return None
    if_exists = data.get("IfExistsResult")
    if if_exists == 1:
        return False  # definitively no such account
    if if_exists != 0:
        return None  # 5/6 = federated/managed -> can't tell

    # GetCredentialType says it exists — confirm with Autodiscover before trusting it.
    return True if await _autodiscover_ok(email, timeout) else None


async def m365_resolve(
    full_name: str, domain: str, max_candidates: int = 6, timeout: float = 12.0
) -> str | None:
    """Brute-force a person's common email formats against the M365 mailbox check and
    return the first address Microsoft confirms exists. Keyless RCPT-equivalent: turns a
    name + domain into a *verified* mailbox with no email corpus and no SMTP."""
    from internhunter.contacts.email.permute import permutations, split_name

    split = split_name(full_name)
    if split is None:
        return None
    first, last = split
    for email in permutations(first, last, domain)[:max_candidates]:
        if await m365_confirms(email, timeout) is True:
            return email
    return None
