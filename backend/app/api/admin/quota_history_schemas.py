from datetime import datetime

from pydantic import BaseModel

from backend.app.domain.credits import QuotaHistoryPoint


class QuotaHistoryPointResponse(BaseModel):
    """The last remaining balance observed in one UTC hour."""

    hour: datetime
    remaining: int


class QuotaHistoryResponse(BaseModel):
    """Hourly points, oldest first; an hour with no upstream call has no point."""

    days: int
    points: list[QuotaHistoryPointResponse]

    @classmethod
    def from_domain(cls, days: int, points: list[QuotaHistoryPoint]) -> "QuotaHistoryResponse":
        return cls(
            days=days,
            points=[
                QuotaHistoryPointResponse(hour=point.hour, remaining=point.remaining)
                for point in points
            ],
        )
