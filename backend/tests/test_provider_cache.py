import threading

import pytest

from backend.app.application.provider_cache import ProviderPayload
from backend.app.infrastructure.caching.in_process_cache import InProcessProviderCache

PAYLOAD: ProviderPayload = [{"id": "evt-1"}]
OTHER_PAYLOAD: ProviderPayload = [{"id": "evt-2"}]


class ManualClock:
    """Hand-advanced clock, so ageing is asserted rather than slept through."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingLoader:
    def __init__(self, payload: ProviderPayload = PAYLOAD) -> None:
        self._payload = payload
        self.calls = 0

    def __call__(self) -> ProviderPayload:
        self.calls += 1
        return self._payload


class TestIncidentalReuse:
    def test_repeat_fetch_within_ttl_serves_cache(self) -> None:
        loader = RecordingLoader()
        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())

        first = cache.fetch("nfl", loader, live=False)
        second = cache.fetch("nfl", loader, live=False)

        assert loader.calls == 1
        assert first.upstream_contacted is True
        assert second.upstream_contacted is False
        assert second.payload == PAYLOAD

    def test_fetch_past_the_ttl_loads_again(self) -> None:
        loader = RecordingLoader()
        clock = ManualClock()
        cache = InProcessProviderCache(ttl_seconds=300, clock=clock)

        cache.fetch("nfl", loader, live=False)
        clock.advance(301)
        second = cache.fetch("nfl", loader, live=False)

        assert loader.calls == 2
        assert second.upstream_contacted is True

    def test_zero_ttl_disables_reuse(self) -> None:
        """`0` disables reuse — the contract already published for the setting."""
        loader = RecordingLoader()
        cache = InProcessProviderCache(ttl_seconds=0, clock=ManualClock())

        cache.fetch("nfl", loader, live=False)
        cache.fetch("nfl", loader, live=False)

        assert loader.calls == 2

    def test_age_is_reported_against_the_load_not_the_read(self) -> None:
        loader = RecordingLoader()
        clock = ManualClock()
        cache = InProcessProviderCache(ttl_seconds=300, clock=clock)

        cache.fetch("nfl", loader, live=False)
        clock.advance(42)
        served = cache.fetch("nfl", loader, live=False)

        assert served.age_seconds == pytest.approx(42)

    def test_keys_do_not_share_entries(self) -> None:
        nfl = RecordingLoader(PAYLOAD)
        mlb = RecordingLoader(OTHER_PAYLOAD)
        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())

        assert cache.fetch("nfl", nfl, live=False).payload == PAYLOAD
        assert cache.fetch("mlb", mlb, live=False).payload == OTHER_PAYLOAD
        assert nfl.calls == 1
        assert mlb.calls == 1


class TestExplicitRefresh:
    def test_a_refresh_never_serves_an_entry_that_predates_it(self) -> None:
        """The headline rule: a deliberate refresh always pulls live."""
        loader = RecordingLoader()
        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())

        cache.fetch("nfl", loader, live=False)
        refreshed = cache.fetch("nfl", loader, live=True)

        assert loader.calls == 2
        assert refreshed.upstream_contacted is True
        assert refreshed.age_seconds == 0.0

    def test_a_refresh_arriving_after_a_load_completes_pulls_live(self) -> None:
        loader = RecordingLoader()
        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())

        cache.fetch("nfl", loader, live=True)
        cache.fetch("nfl", loader, live=True)

        assert loader.calls == 2

    def test_a_live_load_also_satisfies_later_incidental_reads(self) -> None:
        loader = RecordingLoader()
        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())

        cache.fetch("nfl", loader, live=True)
        incidental = cache.fetch("nfl", loader, live=False)

        assert loader.calls == 1
        assert incidental.upstream_contacted is False


class TestCoalescing:
    def test_concurrent_refreshes_share_one_upstream_call(self) -> None:
        """Three simultaneous refreshes, one upstream call, nobody served stale.

        The two late callers arrive while the first load is still running, so the
        result they receive was fetched after they clicked — which is why sharing
        it does not violate the always-live rule.
        """
        loader_entered = threading.Event()
        release_loader = threading.Event()
        calls: list[str] = []
        calls_guard = threading.Lock()

        def blocking_loader() -> ProviderPayload:
            with calls_guard:
                calls.append("load")
            loader_entered.set()
            assert release_loader.wait(timeout=5), "loader was never released"
            return PAYLOAD

        cache = InProcessProviderCache(ttl_seconds=300)
        results: dict[str, bool] = {}
        results_guard = threading.Lock()

        def refresh(name: str) -> None:
            response = cache.fetch("nfl", blocking_loader, live=True)
            with results_guard:
                results[name] = response.upstream_contacted
                assert response.payload == PAYLOAD

        first = threading.Thread(target=refresh, args=("first",))
        first.start()
        assert loader_entered.wait(timeout=5), "first loader never started"

        # Both of these arrive while the first load is in flight.
        followers = [threading.Thread(target=refresh, args=(name,)) for name in ("b", "c")]
        for thread in followers:
            thread.start()

        release_loader.set()
        for thread in [first, *followers]:
            thread.join(timeout=5)
            assert not thread.is_alive(), "a refresh thread deadlocked"

        assert calls == ["load"]
        assert results == {"first": True, "b": False, "c": False}

    def test_concurrent_fetches_for_different_keys_do_not_block_each_other(self) -> None:
        first_entered = threading.Event()
        release_first = threading.Event()

        def blocking_loader() -> ProviderPayload:
            first_entered.set()
            assert release_first.wait(timeout=5)
            return PAYLOAD

        cache = InProcessProviderCache(ttl_seconds=300)
        blocked = threading.Thread(
            target=lambda: cache.fetch("nfl", blocking_loader, live=True)
        )
        blocked.start()
        assert first_entered.wait(timeout=5)

        # A different key must not queue behind the in-flight nfl load.
        mlb = RecordingLoader(OTHER_PAYLOAD)
        response = cache.fetch("mlb", mlb, live=True)

        assert response.payload == OTHER_PAYLOAD
        release_first.set()
        blocked.join(timeout=5)
        assert not blocked.is_alive()


class TestFailureHandling:
    def test_a_failed_load_is_not_cached(self) -> None:
        attempts: list[int] = []

        def flaky_loader() -> ProviderPayload:
            attempts.append(len(attempts))
            if len(attempts) == 1:
                raise RuntimeError("upstream is down")
            return PAYLOAD

        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())

        with pytest.raises(RuntimeError, match="upstream is down"):
            cache.fetch("nfl", flaky_loader, live=False)

        recovered = cache.fetch("nfl", flaky_loader, live=False)

        assert len(attempts) == 2
        assert recovered.payload == PAYLOAD
        assert recovered.upstream_contacted is True

    def test_a_failed_load_releases_the_key_lock(self) -> None:
        """A raising loader must not leave the key locked for everyone else."""

        def failing_loader() -> ProviderPayload:
            raise RuntimeError("boom")

        cache = InProcessProviderCache(ttl_seconds=300, clock=ManualClock())
        with pytest.raises(RuntimeError):
            cache.fetch("nfl", failing_loader, live=True)

        survivor = RecordingLoader()
        finished = threading.Event()

        def second_attempt() -> None:
            cache.fetch("nfl", survivor, live=True)
            finished.set()

        thread = threading.Thread(target=second_attempt)
        thread.start()
        thread.join(timeout=5)

        assert finished.is_set(), "key lock was not released after a failed load"
        assert survivor.calls == 1
