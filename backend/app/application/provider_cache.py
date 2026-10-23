"""Port for reusing provider responses without ever serving a stale refresh.

Kept adjacent to `ports.py` rather than inside it because the cache carries a
result type of its own, and `ports.py` is otherwise a flat list of Protocols.
"""

from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict

ProviderPayload = list[dict[str, Any]]


class CachedResponse(BaseModel):
    """A payload plus the two facts a caller needs to report honestly.

    `upstream_contacted` is whether *this* call ran the loader, not whether the
    payload originated upstream at some point — everything here did. `age_seconds`
    is how long ago the payload was loaded, which is `0.0` for a fresh load.
    """

    model_config = ConfigDict(frozen=True)

    payload: ProviderPayload
    upstream_contacted: bool
    age_seconds: float


class ProviderResponseCache(Protocol):
    def fetch(
        self,
        key: str,
        loader: Callable[[], ProviderPayload],
        *,
        live: bool,
    ) -> CachedResponse: ...
