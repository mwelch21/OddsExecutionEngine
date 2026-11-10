from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.system_status import ComponentName, ComponentState, ComponentStatus


class ComponentStatusResponse(BaseModel):
    """One component's state, read from one signal. The API row is UI-side.

    `observed_at` is when the signal was read; for the provider it is when its
    newest answer came back, since that answer is the signal.
    """

    component: ComponentName
    state: ComponentState
    observed_at: datetime

    @classmethod
    def from_domain(cls, status: ComponentStatus) -> "ComponentStatusResponse":
        return cls(component=status.component, state=status.state, observed_at=status.observed_at)


class ComponentStatusListResponse(BaseModel):
    components: list[ComponentStatusResponse]

    @classmethod
    def from_domain(cls, statuses: list[ComponentStatus]) -> "ComponentStatusListResponse":
        return cls(components=[ComponentStatusResponse.from_domain(s) for s in statuses])
