from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from internhunter.core.fetch import FetchContext
from internhunter.core.models import NormalizedJob


class Tier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


@dataclass(frozen=True)
class BoardRef:
    ats: str
    token: str
    company: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class RawPosting:
    raw: dict[str, Any]
    detail: dict[str, Any] | None = None
    element: Any = None


class Source(ABC):
    ats: str
    tier: Tier
    needs_browser: bool = False

    @abstractmethod
    def board_url(self, ref: BoardRef) -> str: ...

    @abstractmethod
    def fetch(self, ref: BoardRef, ctx: FetchContext) -> AsyncIterator[RawPosting]: ...

    @abstractmethod
    def normalize(self, raw: RawPosting, ref: BoardRef) -> NormalizedJob: ...

    async def poll(self, ref: BoardRef, ctx: FetchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        async for raw in self.fetch(ref, ctx):
            try:
                jobs.append(self.normalize(raw, ref))
            except Exception as exc:
                ctx.logger.warning("normalize failed for {} {}: {}", self.ats, ref.token, exc)
        return jobs


SOURCE_REGISTRY: dict[str, Source] = {}


def register_source(cls: type[Source]) -> type[Source]:
    instance = cls()
    SOURCE_REGISTRY[instance.ats] = instance
    return cls
