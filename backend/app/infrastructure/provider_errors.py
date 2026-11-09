"""Which refresh error code a provider failure gets (#103).

The one table from the provider's exceptions to the closed `RefreshErrorCode` set.
It lives here, beside the HTTP client, because only the adapter knows its
transport's exceptions; the domain codes what it can tell on its own.
"""

import json

import httpx

from backend.app.domain.refresh_records import RefreshErrorCode, classify_domain_error


def classify_provider_error(error: Exception) -> RefreshErrorCode:
    if isinstance(error, httpx.HTTPStatusError):
        return RefreshErrorCode.UPSTREAM_HTTP
    # Timeouts and failed connects alike: the provider could not be reached in time.
    if isinstance(error, httpx.TransportError):
        return RefreshErrorCode.UPSTREAM_TIMEOUT
    if isinstance(error, httpx.DecodingError | json.JSONDecodeError):
        return RefreshErrorCode.INVALID_RESPONSE
    return classify_domain_error(error)
