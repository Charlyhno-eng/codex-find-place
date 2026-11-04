"""AI adapters. Select a module:object factory via FIND_PLACE_PROVIDER.

Adapters implement async analyze(job, stage, instruction, images) -> Report.
Image paths are relative to job.directory; job.event reports progress.
Adapters must clean up subprocesses on cancellation and return a validated Report.
"""
import importlib
import os
from typing import Protocol
from ..models import Report

class Provider(Protocol):
    async def analyze(self, job, stage: str, instruction: str, images: list[str]) -> Report: ...

class CodexProvider:
    async def analyze(self, job, stage, instruction, images):
        from .codex import codex_pass
        return await codex_pass(job, stage, instruction, images)

def get_provider() -> Provider:
    target = os.getenv("FIND_PLACE_PROVIDER")
    if not target:
        return CodexProvider()
    module, name = target.split(":", 1)
    return getattr(importlib.import_module(module), name)()
