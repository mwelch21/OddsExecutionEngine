from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.credits import CreditBurn
from backend.app.domain.quota import UpstreamCallKind


class SportBurnResponse(BaseModel):
    sport: str
    credits: int
    calls: int


class KindBurnResponse(BaseModel):
    kind: UpstreamCallKind
    credits: int
    calls: int


class CreditBurnResponse(BaseModel):
    """Credits spent in one UTC calendar month, most first.

    Counted per upstream call: refreshes coalesced onto one call count once. Balance
    checks name no sport, so they show under `by_kind` only.
    """

    month: str
    starts_at: datetime
    ends_at: datetime
    total_credits: int
    total_calls: int
    by_sport: list[SportBurnResponse]
    by_kind: list[KindBurnResponse]

    @classmethod
    def from_domain(cls, burn: CreditBurn) -> "CreditBurnResponse":
        return cls(
            month=burn.month,
            starts_at=burn.starts_at,
            ends_at=burn.ends_at,
            total_credits=burn.total_credits,
            total_calls=burn.total_calls,
            by_sport=[
                SportBurnResponse(sport=s.sport_key, credits=s.credits, calls=s.calls)
                for s in burn.by_sport
            ],
            by_kind=[
                KindBurnResponse(kind=k.kind, credits=k.credits, calls=k.calls)
                for k in burn.by_kind
            ],
        )
