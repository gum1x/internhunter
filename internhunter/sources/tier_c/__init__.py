from __future__ import annotations

from importlib import import_module

from loguru import logger

_POLLER_MODULES = [
    "internhunter.sources.tier_c.workday",
    "internhunter.sources.tier_c.icims",
    "internhunter.sources.tier_c.ultipro",
    "internhunter.sources.tier_c.oracle_cloud",
    "internhunter.sources.tier_c.adp",
    "internhunter.sources.tier_c.paylocity",
    "internhunter.sources.tier_c.eightfold",
    "internhunter.sources.tier_c.phenom",
    "internhunter.sources.tier_c.successfactors",
    "internhunter.sources.tier_c.taleo",
    "internhunter.sources.tier_c.neogov",
]

for _module in _POLLER_MODULES:
    try:
        import_module(_module)
    except ImportError as exc:
        logger.debug("tier_c poller not yet available: {} ({})", _module, exc)
