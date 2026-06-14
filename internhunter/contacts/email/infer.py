from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from internhunter.contacts.email.permute import (
    TEMPLATES,
    name_part_variants,
    split_name,
)


@dataclass
class PatternInference:
    template: str | None  # dominant template, or None if undetermined
    votes: int  # how many known emails matched the dominant template
    samples: int  # how many (name,email) pairs we could evaluate


def _localpart(email: str) -> str:
    return email.split("@", 1)[0].lower()


def _domain(email: str) -> str:
    return email.split("@", 1)[1].lower() if "@" in email else ""


def templates_matching(full_name: str, email: str, domain: str) -> list[str]:
    """Which templates would produce this email's localpart for this person's name."""
    if _domain(email) != domain.lower():
        return []
    split = split_name(full_name)
    if split is None:
        return []
    first, last = split
    local = _localpart(email)
    matches: list[str] = []
    for template in TEMPLATES:
        for parts in name_part_variants(first, last):
            rendered = template.format(
                first=parts.first, last=parts.last, f=parts.f, l=parts.l
            )
            if rendered == local:
                matches.append(template)
                break
    return matches


def lock_from_verified(verified_pairs: list[tuple[str, str]], domain: str) -> str | None:
    """A single REAL (name, email) pair locks the company format if it maps to exactly
    one template. Real = GitHub commit/profile email or a mailbox-confirmed address — so
    one confirmed engineer email gives company-wide pattern coverage (vs needing votes>=2).
    """
    for full_name, email in verified_pairs:
        matches = templates_matching(full_name, email, domain)
        if len(matches) == 1:
            return matches[0]
    return None


def infer_pattern(
    known_pairs: list[tuple[str, str]],
    domain: str,
) -> PatternInference:
    """Infer the dominant email template from known (full_name, email) pairs.

    Each pair votes for every template that could have produced it; the template
    with the most votes (requiring >=2 to "lock") wins.
    """
    counter: Counter[str] = Counter()
    samples = 0
    for full_name, email in known_pairs:
        matches = templates_matching(full_name, email, domain)
        if matches:
            samples += 1
            for template in matches:
                counter[template] += 1
    if not counter:
        return PatternInference(template=None, votes=0, samples=samples)
    template, votes = counter.most_common(1)[0]
    if votes < 2:
        # Single weak sample: report it but the caller treats K=1 as low confidence.
        return PatternInference(template=template, votes=votes, samples=samples)
    return PatternInference(template=template, votes=votes, samples=samples)
