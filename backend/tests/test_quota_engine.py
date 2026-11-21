from datetime import UTC, datetime, timedelta

from backend.app.domain.quota import (
    QuotaObservation,
    QuotaReading,
    QuotaSource,
    UpstreamCallKind,
)
from backend.app.engines.quota_engine import QuotaEngine

T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
engine = QuotaEngine()


def _observation(remaining: int | None, used: int | None = 0) -> QuotaObservation:
    return QuotaObservation(
        remaining=remaining,
        used=used,
        source=QuotaSource.HEADERS,
        observed_at=T0,
    )


# --- observe: headers first, local count as fallback ---


def test_headers_are_the_observation_when_present() -> None:
    reading = QuotaReading(
        credits_remaining=497, credits_used=3, estimated_cost=3, observed_at=T0
    )

    observation = engine.observe(reading, previous=_observation(remaining=500))

    assert (observation.remaining, observation.used) == (497, 3)
    assert observation.source is QuotaSource.HEADERS
    assert observation.out_of_credits is False


def test_absent_headers_fall_back_to_the_local_markets_x_regions_count() -> None:
    reading = QuotaReading(estimated_cost=3, observed_at=T0 + timedelta(minutes=5))

    observation = engine.observe(reading, previous=_observation(remaining=100, used=400))

    assert (observation.remaining, observation.used) == (97, 403)
    assert observation.source is QuotaSource.LOCAL


def test_local_count_never_goes_below_zero() -> None:
    reading = QuotaReading(estimated_cost=3, observed_at=T0)

    observation = engine.observe(reading, previous=_observation(remaining=2, used=498))

    assert observation.remaining == 0


def test_local_count_with_no_history_knows_nothing() -> None:
    observation = engine.observe(QuotaReading(estimated_cost=3, observed_at=T0), previous=None)

    assert (observation.remaining, observation.used) == (None, None)
    assert observation.source is QuotaSource.LOCAL


def test_out_of_credits_reads_as_zero_remaining() -> None:
    reading = QuotaReading(out_of_credits=True, estimated_cost=3, observed_at=T0)

    observation = engine.observe(reading, previous=_observation(remaining=4, used=496))

    assert observation.out_of_credits is True
    assert (observation.remaining, observation.used) == (0, 496)


# --- floor: set by the operator, or 10% of the plan ---


def test_floor_defaults_to_ten_percent_of_used_plus_remaining() -> None:
    assert engine.floor(None, _observation(remaining=200, used=300)) == 50


def test_operator_floor_wins_over_the_derived_one() -> None:
    assert engine.floor(80, _observation(remaining=200, used=300)) == 80


def test_floor_is_unknown_without_a_plan_to_derive_it_from() -> None:
    assert engine.floor(None, _observation(remaining=None, used=None)) is None


# --- should_warn: previous >= floor > now, re-armed by rising back ---


def test_crossing_below_the_floor_warns() -> None:
    assert engine.should_warn(_observation(50), _observation(47), floor=50) is True


def test_staying_below_the_floor_does_not_warn_again() -> None:
    assert engine.should_warn(_observation(47), _observation(44), floor=50) is False


def test_staying_above_the_floor_does_not_warn() -> None:
    assert engine.should_warn(_observation(60), _observation(57), floor=50) is False


def test_rising_back_above_the_floor_re_arms_the_warning() -> None:
    rose = engine.should_warn(_observation(44), _observation(500), floor=50)
    crossed_again = engine.should_warn(_observation(500), _observation(49), floor=50)

    assert (rose, crossed_again) == (False, True)


def test_first_observation_already_below_the_floor_warns() -> None:
    assert engine.should_warn(None, _observation(10), floor=50) is True


def test_unknown_remaining_or_floor_never_warns() -> None:
    assert engine.should_warn(_observation(60), _observation(None), floor=50) is False
    assert engine.should_warn(_observation(60), _observation(10), floor=None) is False


# --- paused: Auto-Refresh stays on but stops spending ---


def test_out_of_credits_or_zero_remaining_pauses() -> None:
    out = QuotaObservation(
        remaining=0, used=500, source=QuotaSource.HEADERS, out_of_credits=True, observed_at=T0
    )

    assert engine.is_paused(out) is True
    assert engine.is_paused(_observation(0)) is True
    assert engine.is_paused(_observation(1)) is False
    assert engine.is_paused(None) is False


# --- what the call was and what it spent (#104) ---


def test_an_observation_keeps_the_calls_kind_sport_event_and_cost_header() -> None:
    reading = QuotaReading(
        kind=UpstreamCallKind.EVENT,
        sport_key="icehockey_nhl",
        event_id="abc123",
        credits_remaining=497,
        credits_used=3,
        credits_spent=2,
        estimated_cost=3,
        observed_at=T0,
    )

    observation = engine.observe(reading, previous=None)

    assert observation.kind is UpstreamCallKind.EVENT
    assert (observation.sport_key, observation.event_id) == ("icehockey_nhl", "abc123")
    assert observation.credits_spent == 2


def test_without_a_cost_header_the_spend_is_the_local_count() -> None:
    reading = QuotaReading(kind=UpstreamCallKind.SPORT, estimated_cost=3, observed_at=T0)

    assert engine.observe(reading, previous=None).credits_spent == 3


def test_a_refused_call_spends_nothing() -> None:
    reading = QuotaReading(out_of_credits=True, estimated_cost=3, observed_at=T0)

    assert engine.observe(reading, previous=None).credits_spent == 0


def test_a_balance_check_spends_nothing() -> None:
    reading = QuotaReading(
        kind=UpstreamCallKind.BALANCE_CHECK, credits_remaining=40, estimated_cost=0, observed_at=T0
    )

    observation = engine.observe(reading, previous=None)

    assert (observation.kind, observation.credits_spent) == (UpstreamCallKind.BALANCE_CHECK, 0)


def test_a_zero_balance_is_out_of_credits_even_without_a_refusal() -> None:
    assert engine.is_out_of_credits(_observation(remaining=0)) is True
    assert engine.is_out_of_credits(_observation(remaining=1)) is False
    assert engine.is_out_of_credits(None) is False


def test_without_a_balance_header_the_cost_header_is_what_comes_off_the_balance() -> None:
    reading = QuotaReading(credits_spent=1, estimated_cost=3, observed_at=T0)

    observation = engine.observe(reading, previous=_observation(remaining=100, used=400))

    assert (observation.remaining, observation.used, observation.credits_spent) == (99, 401, 1)
