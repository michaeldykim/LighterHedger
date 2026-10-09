"""Interfaces used by the strategy, independent of exchange transport and clocks."""
import secrets
import time
from typing import Protocol

from .strategy import Spec


class ExchangePort(Protocol):
    """Snapshots and history use the order fields consumed by strategy.matches.

    A None snapshot means an inconsistent read; a None lookup means unknown
    history, never an inferred fill. create must not retry uncertain submissions.
    Snapshot read_at and Runtime.monotonic must use the same clock.
    """

    async def snapshot(self) -> dict | None: ...

    async def lookup(self, watch: dict) -> dict | None: ...

    async def create(self, spec: Spec, client_id: int) -> None: ...


class Runtime(Protocol):
    def monotonic(self) -> float: ...

    def time(self) -> float: ...

    def next_client_id(self) -> int: ...


class LiveRuntime:
    """Preserve the production clock and unpredictable client order identities."""

    def monotonic(self):
        return time.monotonic()

    def time(self):
        return time.time()

    def next_client_id(self):
        return secrets.randbelow(2**48 - 1) + 1
