from datetime import UTC, datetime

import pytest

from backend.app.domain.quota import UpstreamCallOutcome
from backend.app.domain.system_status import (
    ComponentName,
    ComponentState,
    ProviderAnswer,
    SystemSignals,
)
from backend.app.engines.component_status_engine import ComponentStatusEngine

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
ANSWERED_AT = datetime(2026, 11, 8, 11, 55, tzinfo=UTC)


def _signals(**changes: object) -> SystemSignals:
    values: dict[str, object] = {
        "database_reachable": True,
        "notifier_listeners": 1,
        "provider_answer": None,
        "observed_at": NOW,
    }
    values.update(changes)
    return SystemSignals.model_validate(values)


def _state(signals: SystemSignals, component: ComponentName) -> ComponentState:
    statuses = ComponentStatusEngine().statuses(signals)
    return next(status.state for status in statuses if status.component is component)


def _answer(outcome: UpstreamCallOutcome | None) -> ProviderAnswer:
    return ProviderAnswer(outcome=outcome, observed_at=ANSWERED_AT)


def test_reports_database_notifier_and_provider_in_that_order() -> None:
    statuses = ComponentStatusEngine().statuses(_signals())

    assert [status.component for status in statuses] == [
        ComponentName.DATABASE,
        ComponentName.NOTIFIER,
        ComponentName.PROVIDER,
    ]


@pytest.mark.parametrize(
    ("reachable", "state"),
    [(True, ComponentState.HEALTHY), (False, ComponentState.UNHEALTHY)],
)
def test_database_is_healthy_only_when_select_one_answers(
    reachable: bool, state: ComponentState
) -> None:
    assert _state(_signals(database_reachable=reachable), ComponentName.DATABASE) is state


@pytest.mark.parametrize(
    ("listeners", "state"),
    [
        (1, ComponentState.CONNECTED),
        (2, ComponentState.CONNECTED),
        (0, ComponentState.DISCONNECTED),
        (None, ComponentState.UNKNOWN),
    ],
)
def test_notifier_is_connected_while_its_listener_connection_is_open(
    listeners: int | None, state: ComponentState
) -> None:
    assert _state(_signals(notifier_listeners=listeners), ComponentName.NOTIFIER) is state


@pytest.mark.parametrize(
    ("answer", "state"),
    [
        # No upstream call yet.
        (None, ComponentState.UNKNOWN),
        # A call recorded before outcomes were kept: never read as Healthy.
        (_answer(None), ComponentState.UNKNOWN),
        (_answer(UpstreamCallOutcome.ANSWERED), ComponentState.HEALTHY),
        # Out of credits is an answer, not a failure: it shows under metrics.
        (_answer(UpstreamCallOutcome.OUT_OF_CREDITS), ComponentState.HEALTHY),
        # Any other 4xx rejects our request; the provider is up.
        (_answer(UpstreamCallOutcome.CLIENT_ERROR), ComponentState.HEALTHY),
        (_answer(UpstreamCallOutcome.NETWORK_ERROR), ComponentState.UNHEALTHY),
        (_answer(UpstreamCallOutcome.SERVER_ERROR), ComponentState.UNHEALTHY),
        (_answer(UpstreamCallOutcome.AUTH_FAILURE), ComponentState.UNHEALTHY),
    ],
)
def test_provider_state_follows_the_newest_upstream_call(
    answer: ProviderAnswer | None, state: ComponentState
) -> None:
    assert _state(_signals(provider_answer=answer), ComponentName.PROVIDER) is state


def test_every_call_outcome_maps_to_a_provider_state() -> None:
    for outcome in UpstreamCallOutcome:
        assert _state(
            _signals(provider_answer=_answer(outcome)), ComponentName.PROVIDER
        ) is not ComponentState.UNKNOWN


def test_unreachable_database_leaves_the_other_signals_unknown() -> None:
    statuses = ComponentStatusEngine().statuses(
        _signals(database_reachable=False, notifier_listeners=None)
    )

    assert [status.state for status in statuses] == [
        ComponentState.UNHEALTHY,
        ComponentState.UNKNOWN,
        ComponentState.UNKNOWN,
    ]


def test_database_and_notifier_are_observed_now_and_the_provider_at_its_answer() -> None:
    statuses = ComponentStatusEngine().statuses(
        _signals(provider_answer=_answer(UpstreamCallOutcome.ANSWERED))
    )

    assert [status.observed_at for status in statuses] == [NOW, NOW, ANSWERED_AT]


def test_provider_with_no_answer_yet_is_observed_now() -> None:
    statuses = ComponentStatusEngine().statuses(_signals())

    assert statuses[2].observed_at == NOW


@pytest.mark.parametrize(
    ("remaining", "floor", "below"),
    [
        (99, 100, True),
        (100, 100, False),
        (0, 100, True),
        (None, 100, False),
        (50, None, False),
    ],
)
def test_credits_are_below_the_floor_only_when_both_are_known(
    remaining: int | None, floor: int | None, below: bool
) -> None:
    assert ComponentStatusEngine().credits_below_floor(remaining, floor) is below
