from backend.app.domain.quota import UpstreamCallOutcome
from backend.app.domain.system_status import (
    ComponentName,
    ComponentState,
    ComponentStatus,
    ProviderAnswer,
    SystemSignals,
)

# The provider could not be reached, broke, would not let us in or serve us, or
# answered with nothing usable (#92, #121).
_PROVIDER_FAILURES = frozenset(
    {
        UpstreamCallOutcome.NETWORK_ERROR,
        UpstreamCallOutcome.SERVER_ERROR,
        UpstreamCallOutcome.AUTH_FAILURE,
        UpstreamCallOutcome.RATE_LIMITED,
        UpstreamCallOutcome.INVALID_RESPONSE,
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
                observed_at=now if answer is None else answer.observed_at,
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
        # No call yet, or a call recorded before outcomes were kept: never Healthy.
        if answer is None or answer.outcome is None:
            return ComponentState.UNKNOWN
        if answer.outcome in _PROVIDER_FAILURES:
            return ComponentState.UNHEALTHY
        # Out of credits is an answer, not a failure; so is any other 4xx but 429,
        # which rejects our request and proves the provider is up.
        return ComponentState.HEALTHY
