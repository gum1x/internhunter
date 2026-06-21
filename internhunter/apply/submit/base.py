from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from internhunter.apply.fields import FormField


@dataclass
class FormSpec:
    fields: list[FormField]
    requires_account: bool = False
    captcha_detected: bool = False


@dataclass
class SubmitResult:
    status: str
    confirmation: str | None = None
    reason: str | None = None


class Submitter(ABC):
    ats: str

    @abstractmethod
    async def probe_form(self, job, ctx) -> FormSpec: ...

    @abstractmethod
    async def submit(self, job, ctx, payload: dict[str, str], resume_path) -> SubmitResult: ...


SUBMITTER_REGISTRY: dict[str, Submitter] = {}


def register_submitter(cls: type[Submitter]) -> type[Submitter]:
    SUBMITTER_REGISTRY[cls.ats] = cls()
    return cls


def get_submitter(ats: str) -> Submitter | None:
    return SUBMITTER_REGISTRY.get(ats)
