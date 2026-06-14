from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Canonical corporate email templates, most-common first. ``{f}``/``{l}`` are first
# initials of first/last; ``{first}``/``{last}`` are full tokens. Separators (".", "_",
# "-", "") are expanded by ``_apply``.
TEMPLATES: list[str] = [
    "{first}.{last}",
    "{f}{last}",
    "{first}{last}",
    "{first}",
    "{first}_{last}",
    "{first}-{last}",
    "{f}.{last}",
    "{first}{l}",
    "{last}.{first}",
    "{last}{first}",
    "{f}{l}",
    "{last}",
    "{last}.{f}",
    "{f}_{last}",
]


@dataclass(frozen=True)
class NameParts:
    first: str
    last: str
    f: str
    l: str  # noqa: E741 - mirrors the {l} template token


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped


def normalize_token(value: str) -> str:
    """Lowercase ascii localpart token: strip accents, drop apostrophes/spaces/dots."""
    ascii_value = _strip_accents(value)
    try:
        from unidecode import unidecode

        ascii_value = unidecode(ascii_value)
    except Exception:
        pass
    out = []
    for ch in ascii_value.lower():
        if ch.isalnum():
            out.append(ch)
        # drop apostrophes, spaces, dots; hyphens handled by name_variants
    return "".join(out)


def split_name(full_name: str) -> tuple[str, str] | None:
    """Split a display name into (first, last). Returns None if not splittable."""
    parts = [p for p in full_name.replace(",", " ").split() if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def _hyphen_variants(token: str) -> list[str]:
    """For 'anne-marie' yield ['annemarie', 'anne'] (drop-hyphen, first-segment)."""
    if "-" not in token:
        return [token]
    joined = token.replace("-", "")
    first_seg = token.split("-", 1)[0]
    seen: list[str] = []
    for variant in (joined, first_seg):
        if variant and variant not in seen:
            seen.append(variant)
    return seen


def name_part_variants(first: str, last: str) -> list[NameParts]:
    """All normalized (first,last) variants accounting for hyphens/accents."""
    first_variants = [normalize_token(v) for v in _hyphen_variants(first)]
    last_variants = [normalize_token(v) for v in _hyphen_variants(last)]
    out: list[NameParts] = []
    seen: set[tuple[str, str]] = set()
    for fv in first_variants:
        for lv in last_variants:
            if not fv or not lv:
                continue
            if (fv, lv) in seen:
                continue
            seen.add((fv, lv))
            out.append(NameParts(first=fv, last=lv, f=fv[0], l=lv[0]))
    return out


def _apply(template: str, parts: NameParts) -> str:
    return template.format(first=parts.first, last=parts.last, f=parts.f, l=parts.l)


def render_pattern(template: str, first: str, last: str) -> str | None:
    """Render one template for a name into a localpart (primary variant)."""
    variants = name_part_variants(first, last)
    if not variants:
        return None
    return _apply(template, variants[0])


def permutations(first: str, last: str, domain: str) -> list[str]:
    """All candidate emails for a person at a domain, ordered by template priority."""
    variants = name_part_variants(first, last)
    out: list[str] = []
    seen: set[str] = set()
    for template in TEMPLATES:
        for parts in variants:
            local = _apply(template, parts)
            email = f"{local}@{domain}"
            if email not in seen:
                seen.add(email)
                out.append(email)
    return out
