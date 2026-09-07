from datetime import UTC, datetime, timedelta

from backend.app.domain.models import MarketType, WatchIntent, WatchStatus

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _watch(
    *,
    expires_at: datetime | None = None,
    status: WatchStatus = WatchStatus.ACTIVE,
) -> WatchIntent:
    return WatchIntent(
        id="watch-1",
        event_id="event-1",
        market_type=MarketType.MONEYLINE,
        selection="knicks",
        target_price=120,
        expires_at=expires_at,
        status=status,
    )


def test_watch_without_ttl_never_expires() -> None:
    assert _watch().is_expired_at(NOW) is False
    assert _watch().effective_status(NOW) is WatchStatus.ACTIVE


def test_watch_past_its_ttl_is_expired() -> None:
    watch = _watch(expires_at=NOW - timedelta(seconds=1))

    assert watch.is_expired_at(NOW) is True
    assert watch.effective_status(NOW) is WatchStatus.EXPIRED


def test_watch_expiring_exactly_now_is_expired() -> None:
    assert _watch(expires_at=NOW).is_expired_at(NOW) is True


def test_watch_with_future_ttl_is_still_active() -> None:
    watch = _watch(expires_at=NOW + timedelta(seconds=1))

    assert watch.is_expired_at(NOW) is False
    assert watch.effective_status(NOW) is WatchStatus.ACTIVE


def test_naive_expiry_from_sqlite_is_treated_as_utc() -> None:
    watch = _watch(expires_at=(NOW - timedelta(minutes=5)).replace(tzinfo=None))

    assert watch.is_expired_at(NOW) is True


def test_cancelled_watch_is_never_relabelled_as_expired() -> None:
    watch = _watch(expires_at=NOW - timedelta(days=1), status=WatchStatus.CANCELLED)

    assert watch.effective_status(NOW) is WatchStatus.CANCELLED


def test_with_effective_status_leaves_unaffected_watches_untouched() -> None:
    watch = _watch()

    assert watch.with_effective_status(NOW) is watch


def test_with_effective_status_projects_without_mutating_stored_status() -> None:
    watch = _watch(expires_at=NOW - timedelta(minutes=1))

    projected = watch.with_effective_status(NOW)

    assert projected.status is WatchStatus.EXPIRED
    assert watch.status is WatchStatus.ACTIVE
