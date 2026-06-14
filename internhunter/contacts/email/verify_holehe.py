from __future__ import annotations

from typing import Any

# holehe checks whether an email is registered on real sites via their
# password-reset / signup endpoints (HTTPS) — so it works despite outbound port 25
# being blocked. A hit is a strong "this mailbox is real" signal.

# Work-relevant, still-leaky sites take priority over consumer/rotted ones — an
# address-keyed exists==True is an honest confirmation signal. Names holehe doesn't ship
# are harmlessly skipped by the hasattr filter below.
_MODULES = (
    "atlassian", "gitlab", "zoom", "adobe", "docker", "zoho", "codecademy",
    "github", "twitter", "instagram", "spotify", "pinterest",
)


async def holehe_confirms(email: str, timeout: float = 20.0) -> bool:
    """True if holehe finds the email registered on at least one known site."""
    try:
        import httpx
        from holehe.core import import_submodules
    except Exception:
        return False
    try:
        modules = import_submodules("holehe.modules")
        funcs = []
        for name, mod in modules.items():
            short = name.split(".")[-1]
            if short in _MODULES and hasattr(mod, short):
                funcs.append(getattr(mod, short))
    except Exception:
        return False
    if not funcs:
        return False

    async with httpx.AsyncClient(timeout=timeout) as client:
        for func in funcs:
            out: list[dict[str, Any]] = []
            try:
                await func(email, client, out)
            except Exception:
                continue
            for entry in out:
                if entry.get("exists") is True:
                    return True
    return False
