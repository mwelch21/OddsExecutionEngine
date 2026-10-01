import threading
import time
from typing import Callable

from backend.app.application.provider_cache import (
    CachedResponse,
    ProviderPayload,
    ProviderResponseCache,
)


class _Entry:
    """A loaded payload, when its load finished, and which load produced it.

    `generation` counts completed loads for this key. It exists because clock
    readings cannot answer "did this load finish after I arrived?" — two readings
    can land in the same tick, and under a coarse clock that makes a refresh
    accept an entry that predates it. A counter answers it exactly, at any clock
    resolution. `loaded_at` is kept only for reporting age.
    """

    __slots__ = ("payload", "loaded_at", "generation")

    def __init__(self, payload: ProviderPayload, loaded_at: float, generation: int) -> None:
        self.payload = payload
        self.loaded_at = loaded_at
        self.generation = generation


class InProcessProviderCache(ProviderResponseCache):
    """Single-process cache that collapses concurrent fetches into one call.

    Two behaviours, and the difference between them is the whole point:

    `live=False` is incidental reuse — a repeat fetch inside one operation, such
    as scanning every configured sport to locate one event. It accepts any entry
    younger than the TTL.

    `live=True` is a deliberate refresh. It never accepts an entry that predates
    the caller. Someone watching a game who sees a play happen and hits refresh
    must get the line as of that click, not the line from a moment before it. So
    a live caller notes the generation it saw on arrival and will only take an
    entry produced by a *later* load.

    That rule is what lets coalescing coexist with "a refresh always pulls live":
    callers who queue behind an in-flight load are served by it, because that
    load finishes after they arrived. Callers who turn up once it has finished
    load again. The saving is on simultaneity, not on sequence.
    """

    def __init__(
        self,
        ttl_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        # Monotonic, not wall-clock: ages must not jump if the system clock is
        # adjusted underneath a running process.
        self._clock = clock or time.monotonic
        self._entries: dict[str, _Entry] = {}
        self._key_locks: dict[str, threading.Lock] = {}
        self._loads_completed = 0
        # Guards the state above. Never held while a loader runs.
        self._guard = threading.Lock()

    def fetch(
        self,
        key: str,
        loader: Callable[[], ProviderPayload],
        *,
        live: bool,
    ) -> CachedResponse:
        arrived_at = self._clock()
        with self._guard:
            entry_on_arrival = self._entries.get(key)
            generation_on_arrival = entry_on_arrival.generation if entry_on_arrival else 0

        if not live and entry_on_arrival is not None:
            if self._within_ttl(entry_on_arrival, arrived_at):
                return self._serve(entry_on_arrival, arrived_at)

        # Serialises callers for this key. The first runs the loader; the rest
        # wait here and then find its result already stored.
        with self._lock_for(key):
            entry = self._entries.get(key)
            if entry is not None and self._is_acceptable(entry, generation_on_arrival, live):
                return self._serve(entry, self._clock())

            # A raising loader leaves no entry behind, so a failed fetch is
            # retried rather than cached as a hole.
            payload = loader()
            loaded_at = self._clock()
            with self._guard:
                self._loads_completed += 1
                self._entries[key] = _Entry(payload, loaded_at, self._loads_completed)

        return CachedResponse(payload=payload, upstream_contacted=True, age_seconds=0.0)

    def _is_acceptable(self, entry: _Entry, generation_on_arrival: int, live: bool) -> bool:
        if live:
            # Strictly later: an entry from the generation we already saw is the
            # one that predates this caller, whatever the clock says.
            return entry.generation > generation_on_arrival
        return self._within_ttl(entry, self._clock())

    def _serve(self, entry: _Entry, now: float) -> CachedResponse:
        return CachedResponse(
            payload=entry.payload,
            upstream_contacted=False,
            age_seconds=max(0.0, now - entry.loaded_at),
        )

    def _within_ttl(self, entry: _Entry, now: float) -> bool:
        # A TTL of 0 disables reuse outright, which is the contract already
        # published for PROVIDER_CACHE_TTL_SECONDS.
        if self._ttl_seconds <= 0:
            return False
        return (now - entry.loaded_at) < self._ttl_seconds

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._key_locks.setdefault(key, threading.Lock())
