from __future__ import annotations

from importlib import import_module

from loguru import logger

_POLLER_MODULES = [
    "internhunter.sources.tier_b.breezy",
    "internhunter.sources.tier_b.jazzhr",
    "internhunter.sources.tier_b.jobvite",
    "internhunter.sources.tier_b.bamboohr",
    "internhunter.sources.tier_b.rippling",
    "internhunter.sources.tier_b.dover",
    "internhunter.sources.tier_b.zohorecruit",
    "internhunter.sources.tier_b.gem",
]

for _module in _POLLER_MODULES:
    try:
        import_module(_module)
    except ImportError as exc:
        logger.debug("tier_b poller not yet available: {} ({})", _module, exc)
