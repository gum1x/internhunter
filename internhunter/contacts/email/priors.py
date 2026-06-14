from __future__ import annotations

# Size-aware email-format priors (Interseller corpus). For real companies (50+ staff)
# the dominant patterns are {f}{last} and {first}.{last}; {first} dominates only tiny orgs.
# We pick the single most likely template per headcount band.
_BAND_DEFAULT_TEMPLATE: dict[str, str] = {
    "tiny": "{first}",  # < ~50 employees
    "mid": "{f}{last}",  # ~50–1000
    "large": "{first}.{last}",  # 1000+
}

# Confidence (0–1) of the prior when used as the *only* signal — deliberately low.
_BAND_PRIOR_CONF: dict[str, float] = {
    "tiny": 0.30,
    "mid": 0.40,
    "large": 0.45,
}


# Provider defaults observed in practice: Microsoft 365 tenants overwhelmingly use
# {first}.{last}; Google Workspace skews {first} for small orgs, {first}.{last} as they grow.
_PROVIDER_TEMPLATE: dict[str, dict[str, str]] = {
    "microsoft": {"tiny": "{first}.{last}", "mid": "{first}.{last}", "large": "{first}.{last}"},
    "google": {"tiny": "{first}", "mid": "{f}{last}", "large": "{first}.{last}"},
}


def default_template(headcount_band: str | None, provider: str = "unknown") -> str:
    """Best-guess template when no same-domain corpus is available, conditioned on the
    mail provider (raises first-try mailbox-check hit-rate) then headcount."""
    band = headcount_band or "large"
    by_provider = _PROVIDER_TEMPLATE.get(provider)
    if by_provider:
        return by_provider.get(band, "{first}.{last}")
    return _BAND_DEFAULT_TEMPLATE.get(band, "{first}.{last}")


def prior_confidence(headcount_band: str | None) -> float:
    return _BAND_PRIOR_CONF.get(headcount_band or "large", 0.40)
