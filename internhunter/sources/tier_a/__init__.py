from __future__ import annotations

from importlib import import_module

from loguru import logger

_POLLER_MODULES = [
    "internhunter.sources.tier_a.greenhouse",
    "internhunter.sources.tier_a.lever",
    "internhunter.sources.tier_a.ashby",
    "internhunter.sources.tier_a.smartrecruiters",
    "internhunter.sources.tier_a.recruitee",
    "internhunter.sources.tier_a.workable",
    "internhunter.sources.tier_a.personio",
]

for _module in _POLLER_MODULES:
    try:
        import_module(_module)
    except ImportError as exc:
        logger.debug("tier_a poller not yet available: {} ({})", _module, exc)
