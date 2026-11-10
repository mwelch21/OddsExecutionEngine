from backend.app.domain.refresh_records import RefreshErrorCode, RefreshOutcomeStatus
from backend.app.domain.system_status import (
    ComponentName,
    ComponentState,
    ComponentStatus,
    ProviderAnswer,
    SystemSignals,
)

# The provider answered, but not with anything usable, or could not be reached.
_PROVIDER_FAILURES = frozenset(
    {
        RefreshErrorCode.UPSTREAM_HTTP,
        RefreshErrorCode.UPSTREAM_TIMEOUT,
        RefreshErrorCode.INVALID_RESPONSE,
    }
)


class ComponentStatusEngine:
    """Maps each signal to its component's state, per read (#92).

    One signal per component, no thresholds, no combined verdict. Nothing is
    stored and no event is emitted. A new component is a new entry here.
    """

    def statuses(self, signals: SystemSignals) -> list[ComponentStatus]:
        now = signals.observed_at
        answer = signals.provider_answer
        return [
            ComponentStatus(
                component=ComponentName.DATABASE,
                state=ComponentState.HEALTHY
                if signals.database_reachable
                else ComponentState.UNHEALTHY,
                observed_at=now,
            ),
            ComponentStatus(
                component=ComponentName.NOTIFIER,
                state=self._notifier(signals.notifier_listeners),
                observed_at=now,
            ),
            ComponentStatus(
                component=ComponentName.PROVIDER,
                state=self._provider(answer),
                observed_at=now if answer is None else answer.finished_at,
            ),
        ]

    def credits_below_floor(self, remaining: int | None, floor: int | None) -> bool:
        """Part of the attention rule: credits strictly below the floor in force."""
        return remaining is not None and floor is not None and remaining < floor

    def _notifier(self, listeners: int | None) -> ComponentState:
        # Connected proves the notifier is listening, not that deliveries succeed;
        # the delivery metrics show that.
        if listeners is None:
            return ComponentState.UNKNOWN
        return ComponentState.CONNECTED if listeners > 0 else ComponentState.DISCONNECTED

    def _provider(self, answer: ProviderAnswer | None) -> ComponentState:
        if answer is None:
            return ComponentState.UNKNOWN
        # Out of credits (`refused`) is an answer, not a failure.
        if answer.outcome is not RefreshOutcomeStatus.FAILED:
            return ComponentState.HEALTHY
        if answer.error_code in _PROVIDER_FAILURES:
            return ComponentState.UNHEALTHY
        # INTERNAL: the refresh broke on our side; it says nothing about the provider.
        # The read already passes such refreshes over; Unknown is the safe answer if
        # one arrives anyway.
        return ComponentState.UNKNOWN
