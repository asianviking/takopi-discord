"""Compatibility shim for EngineRunOptions missing in takopi <0.20.0."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineRunOptions:
    model: str | None = None
    reasoning: str | None = None


@contextmanager
def apply_run_options(options: EngineRunOptions | None) -> Iterator[None]:
    yield
