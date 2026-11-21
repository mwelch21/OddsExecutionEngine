"""Every refresh failure maps to one code from the closed set (#103)."""

import json

import httpx
import pytest

from backend.app.domain.quota import OutOfUsageCreditsError
from backend.app.domain.refresh_records import (
    RefreshErrorCode,
    RefreshOutcomeStatus,
    RefreshResult,
    classify_domain_error,
)
from backend.app.infrastructure.provider_errors import classify_provider_error

REQUEST = httpx.Request("GET", "https://api.the-odds-api.com/v4/sports/basketball/odds")


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        f"{status}", request=REQUEST, response=httpx.Response(status, request=REQUEST)
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_http_status_error(500), RefreshErrorCode.UPSTREAM_HTTP),
        (_http_status_error(401), RefreshErrorCode.UPSTREAM_HTTP),
        (httpx.ReadTimeout("timed out", request=REQUEST), RefreshErrorCode.UPSTREAM_TIMEOUT),
        (httpx.ConnectTimeout("timed out", request=REQUEST), RefreshErrorCode.UPSTREAM_TIMEOUT),
        (httpx.ConnectError("refused", request=REQUEST), RefreshErrorCode.UPSTREAM_TIMEOUT),
        (httpx.DecodingError("bad gzip", request=REQUEST), RefreshErrorCode.INVALID_RESPONSE),
        (json.JSONDecodeError("Expecting value", "<html>", 0), RefreshErrorCode.INVALID_RESPONSE),
        (OutOfUsageCreditsError(), RefreshErrorCode.OUT_OF_USAGE_CREDITS),
        (RuntimeError("boom"), RefreshErrorCode.INTERNAL),
        (KeyError("bookmakers"), RefreshErrorCode.INTERNAL),
    ],
)
def test_the_provider_classifier_maps_each_failure_to_its_code(
    error: Exception, code: RefreshErrorCode
) -> None:
    assert classify_provider_error(error) is code


def test_without_the_provider_the_domain_codes_only_what_it_knows() -> None:
    assert classify_domain_error(OutOfUsageCreditsError()) is (
        RefreshErrorCode.OUT_OF_USAGE_CREDITS
    )
    assert classify_domain_error(_http_status_error(500)) is RefreshErrorCode.INTERNAL


def test_only_out_of_credits_is_refused() -> None:
    refused = RefreshResult.from_error(OutOfUsageCreditsError(), classify_provider_error)
    failed = RefreshResult.from_error(_http_status_error(500), classify_provider_error)
    succeeded = RefreshResult.from_error(None, classify_provider_error)

    assert (refused.outcome, refused.error_code) == (
        RefreshOutcomeStatus.REFUSED,
        RefreshErrorCode.OUT_OF_USAGE_CREDITS,
    )
    assert (failed.outcome, failed.error_code) == (
        RefreshOutcomeStatus.FAILED,
        RefreshErrorCode.UPSTREAM_HTTP,
    )
    assert (succeeded.outcome, succeeded.error_code, succeeded.error) == (
        RefreshOutcomeStatus.SUCCEEDED,
        None,
        None,
    )


def test_the_error_text_keeps_its_detail_without_the_key() -> None:
    error = RuntimeError("500 for url '/odds?apiKey=s3cr3t&regions=us'")

    assert (
        RefreshResult.from_error(error).error == "500 for url '/odds?apiKey=[redacted]&regions=us'"
    )
