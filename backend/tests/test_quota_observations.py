"""Every upstream call hands its quota to the recorder, served or refused (ADR-016)."""

import threading
import time
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from backend.app.domain.quota import (
    OutOfUsageCreditsError,
    QuotaReading,
    UpstreamCallKind,
    linked_observation,
)
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache
from backend.app.infrastructure.odds_api_provider import TheOddsApiProvider

HEADERS = {"x-requests-remaining": "487", "x-requests-used": "13", "x-requests-last": "3"}
EVENT: dict[str, Any] = {
    "id": "abc123",
    "sport_key": "icehockey_nhl",
    "commence_time": "2026-11-05T23:00:00Z",
    "home_team": "Boston Bruins",
    "away_team": "New York Rangers",
    "bookmakers": [],
}


class RecordingQuota:
    """Hands back the reading's position as its observation id, as the store would."""

    def __init__(self, fail: bool = False) -> None:
        self.readings: list[QuotaReading] = []
        self._fail = fail
        self._guard = threading.Lock()

    def record(self, reading: QuotaReading) -> int:
        if self._fail:
            raise RuntimeError("database is down")
        with self._guard:
            self.readings.append(reading)
            return len(self.readings)


def _provider(recorder: RecordingQuota, cache_ttl_seconds: int = 0) -> TheOddsApiProvider:
    return TheOddsApiProvider(
        api_key="test-key",
        regions=["us"],
        markets=["h2h", "spreads", "totals"],
        response_cache=InProcessProviderCache(ttl_seconds=cache_ttl_seconds),
        quota_recorder=recorder,
    )


def _response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.the-odds-api.com/v4/sports"),
    )


def test_a_sport_refresh_records_the_header_quota_and_the_local_cost() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(provider._client, "get", return_value=_response(200, [EVENT], HEADERS)):
        provider.list_quotes_for_sport("icehockey_nhl")

    [reading] = recorder.readings
    assert (reading.credits_remaining, reading.credits_used) == (487, 13)
    assert reading.estimated_cost == 3
    assert reading.out_of_credits is False


def test_a_per_event_refresh_records_its_quota() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(provider._client, "get", return_value=_response(200, EVENT, HEADERS)):
        provider.list_quotes("abc123", "icehockey_nhl")

    assert [r.credits_remaining for r in recorder.readings] == [487]


def test_absent_headers_still_record_a_reading_for_the_local_fallback() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(provider._client, "get", return_value=_response(200, [])):
        provider.list_quotes_for_sport("icehockey_nhl")

    [reading] = recorder.readings
    assert (reading.credits_remaining, reading.credits_used) == (None, None)
    assert reading.estimated_cost == 3


def test_a_failed_call_is_still_recorded_before_it_raises() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with (
        patch.object(provider._client, "get", return_value=_response(500, {}, HEADERS)),
        pytest.raises(httpx.HTTPStatusError),
    ):
        provider.list_quotes_for_sport("icehockey_nhl")

    assert len(recorder.readings) == 1


def test_out_of_usage_credits_is_recorded_and_raised_as_its_own_error() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)
    body = {"message": "Usage quota has been reached", "error_code": "OUT_OF_USAGE_CREDITS"}

    with (
        patch.object(provider._client, "get", return_value=_response(401, body)),
        pytest.raises(OutOfUsageCreditsError),
    ):
        provider.list_quotes_for_sport("icehockey_nhl")

    [reading] = recorder.readings
    assert reading.out_of_credits is True


def test_a_response_the_cache_answered_records_nothing() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder, cache_ttl_seconds=300)

    with patch.object(provider._client, "get", return_value=_response(200, [EVENT], HEADERS)):
        provider.list_events_for_sport("icehockey_nhl")
        provider.list_events_for_sport("icehockey_nhl")

    assert len(recorder.readings) == 1


def test_a_balance_check_calls_the_free_sports_endpoint_and_costs_nothing() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(
        provider._client, "get", return_value=_response(200, [], HEADERS)
    ) as http_get:
        provider.check_quota()

    assert http_get.call_args.args[0] == "https://api.the-odds-api.com/v4/sports"
    [reading] = recorder.readings
    assert (reading.credits_remaining, reading.estimated_cost) == (487, 0)


def test_a_recorder_failure_never_fails_the_refresh() -> None:
    provider = _provider(RecordingQuota(fail=True))

    with patch.object(provider._client, "get", return_value=_response(200, [EVENT], HEADERS)):
        quotes, _ = provider.list_quotes_for_sport("icehockey_nhl")

    assert "abc123" in quotes


# --- what each call was, and which call a refresh used (#104) ---


def test_a_sport_pull_records_its_kind_sport_and_cost() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(provider._client, "get", return_value=_response(200, [EVENT], HEADERS)):
        _, report = provider.list_quotes_for_sport("icehockey_nhl")

    [reading] = recorder.readings
    assert reading.kind is UpstreamCallKind.SPORT
    assert (reading.sport_key, reading.event_id) == ("icehockey_nhl", None)
    assert reading.credits_spent == 3
    assert report.observation_id == 1


def test_an_event_pull_records_its_kind_sport_event_and_cost() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(provider._client, "get", return_value=_response(200, EVENT, HEADERS)):
        _, report = provider.list_quotes("abc123", "icehockey_nhl")

    [reading] = recorder.readings
    assert reading.kind is UpstreamCallKind.EVENT
    assert (reading.sport_key, reading.event_id) == ("icehockey_nhl", "abc123")
    assert reading.credits_spent == 3
    assert report.observation_id == 1


def test_a_balance_check_records_its_kind_and_spends_nothing() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with patch.object(provider._client, "get", return_value=_response(200, [], HEADERS)):
        provider.check_quota()

    [reading] = recorder.readings
    assert reading.kind is UpstreamCallKind.BALANCE_CHECK
    assert (reading.sport_key, reading.event_id) == (None, None)
    # The header repeats the last billed call's cost; a free call spent nothing.
    assert reading.credits_spent == 0


def test_a_failed_call_carries_its_observation_on_the_error() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)

    with (
        patch.object(provider._client, "get", return_value=_response(500, {}, HEADERS)),
        pytest.raises(httpx.HTTPStatusError) as raised,
    ):
        provider.list_quotes_for_sport("icehockey_nhl")

    assert linked_observation(raised.value) == 1


def test_coalesced_refreshes_share_one_observation() -> None:
    recorder = RecordingQuota()
    provider = _provider(recorder)
    entered = threading.Event()
    release = threading.Event()

    def slow_get(*_: Any, **__: Any) -> httpx.Response:
        entered.set()
        assert release.wait(timeout=5), "upstream call was never released"
        return _response(200, [EVENT], HEADERS)

    observation_ids: list[int | None] = []
    guard = threading.Lock()

    def refresh() -> None:
        _, report = provider.list_quotes_for_sport("icehockey_nhl")
        with guard:
            observation_ids.append(report.observation_id)

    with patch.object(provider._client, "get", side_effect=slow_get):
        first = threading.Thread(target=refresh)
        first.start()
        assert entered.wait(timeout=5), "first call never started"
        second = threading.Thread(target=refresh)
        second.start()
        time.sleep(0.1)  # let the second refresh queue behind the call in flight
        release.set()
        for thread in (first, second):
            thread.join(timeout=5)
            assert not thread.is_alive()

    assert len(recorder.readings) == 1
    assert observation_ids == [1, 1]
