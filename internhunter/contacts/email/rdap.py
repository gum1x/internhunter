from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from internhunter.core.fetch import FetchContext

# RDAP is the structured, keyless successor to WHOIS. rdap.org bootstraps to the right
# registry and returns JSON. Registrant contacts live in jCard (vCardArray) blocks on
# each entity; we pull any email properties. Most gTLDs now redact registrant email
# behind privacy, but ccTLDs, older registrations, and registrar abuse contacts often
# still expose a real address — a free lead when nothing else surfaces one.

_RDAP_BASE = "https://rdap.org/domain/"


def _emails_from_vcard(vcard: Any) -> list[str]:
    """vCardArray is ["vcard", [[name, params, type, value], ...]]."""
    if not isinstance(vcard, list) or len(vcard) < 2:
        return []
    props = vcard[1]
    if not isinstance(props, list):
        return []
    out: list[str] = []
    for prop in props:
        if not isinstance(prop, list) or len(prop) < 4:
            continue
        if str(prop[0]).lower() != "email":
            continue
        value = prop[3]
        if isinstance(value, str) and "@" in value:
            out.append(value.strip().lower())
    return out


def _walk_entities(entities: Any, acc: list[str]) -> None:
    if not isinstance(entities, list):
        return
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        acc.extend(_emails_from_vcard(ent.get("vcardArray")))
        # entities can nest (e.g. registrar -> abuse contact)
        _walk_entities(ent.get("entities"), acc)


async def rdap_emails(ctx: FetchContext, domain: str) -> list[str]:
    """Registration-contact emails for ``domain`` via RDAP. Deduped, lowercased.

    Returns an empty list on any failure (network, non-JSON, redacted)."""
    try:
        data = await ctx.get_json(f"{_RDAP_BASE}{domain}", respect_robots=False)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    found: list[str] = []
    _walk_entities(data.get("entities"), found)
    seen: set[str] = set()
    deduped: list[str] = []
    for email in found:
        if email not in seen:
            seen.add(email)
            deduped.append(email)
    return deduped
