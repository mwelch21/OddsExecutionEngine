"""Port for reusing provider responses without ever serving a stale refresh.

Kept adjacent to `ports.py` rather than inside it because the cache carries a
result type of its own, and `ports.py` is otherwise a flat list of Protocols.
"""

from typing import Any, Callable, Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

ProviderPayload = list[dict[str, Any]]

# What a loader returns and the cache stores: a bare payload, or a payload with
# facts about the call that loaded it (the provider keeps its quota observation id
# beside it, so callers coalesced onto one call can name that call).
PayloadT = TypeVar("PayloadT")


class CachedResponse(BaseModel, Generic[PayloadT]):
    """A payload plus the two facts a caller needs to report honestly.

    `upstream_contacted` is whether *this* call ran the loader, not whether the
    payload originated upstream at some point — everything here did. `age_seconds`
    is how long ago the payload was loaded, which is `0.0` for a fresh load.
    """

    model_config = ConfigDict(frozen=True)

    payload: PayloadT
    upstream_contacted: bool
    age_seconds: float


class ProviderResponseCache(Protocol):
    def fetch(
        self,
        key: str,
        loader: Callable[[], PayloadT],
        *,
        live: bool,
    ) -> CachedResponse[PayloadT]: ...
