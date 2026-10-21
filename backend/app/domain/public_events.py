"""Public events: the versioned contract that leaves the system (ADR-014).

Workflow events are the internal audit trail. A public event is what an outside
reader such as the notifier sees: a CloudEvents 1.0 envelope whose `type` carries
the version, and whose `data` matches a JSON Schema under `contracts/events/`.
Nothing is public by default; each type here is a deliberate choice.
"""

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import Field, field_serializer

from backend.app.domain.base import DomainModel
from backend.app.domain.models import MarketType, Opportunity

PUBLIC_EVENT_SOURCE = "/oddsengine"
OPPORTUNITY_IDENTIFIED_V1 = "oddsengine.opportunity.identified.v1"
_SCHEMA_BASE_URL = (
    "https://github.com/mwelch21/OddsExecutionEngine/blob/development/contracts/events"
)


PayloadT = TypeVar("PayloadT", bound=DomainModel, covariant=True)


class PublicEvent(DomainModel, Generic[PayloadT]):
    """Keep payloads typed until serialization into the public outbox.

    Concrete builders specify their payload model. Shared staging ports accept
    PublicEvent[DomainModel] so new event types need no persistence changes.
    """

    id: str
    type: str
    source: str = PUBLIC_EVENT_SOURCE
    specversion: str = "1.0"
    time: datetime
    subject: str | None = None
    dataschema: str
    data: PayloadT

    def to_cloudevent(self) -> dict[str, Any]:
        """The structured-mode JSON form. Unset optional attributes are absent, not null;
        nulls inside `data` are kept, because the schema defines them."""
        envelope = self.model_dump(mode="json")
        if envelope["subject"] is None:
            del envelope["subject"]
        return envelope


class OpportunityEventDetailsV1(DomainModel):
    id: str = Field(min_length=1)
    sport: str | None
    league: str | None
    home: str | None
    away: str | None
    starts_at: datetime | None

    @field_serializer("starts_at", when_used="json")
    def serialize_starts_at(self, value: datetime | None) -> str | None:
        return _iso(value)


class BookPriceV1(DomainModel):
    sportsbook: str = Field(min_length=1)
    price: int


class BestBookPriceV1(BookPriceV1):
    quoted_at: datetime | None

    @field_serializer("quoted_at", when_used="json")
    def serialize_quoted_at(self, value: datetime | None) -> str | None:
        return _iso(value)


class OpportunityIdentifiedDataV1(DomainModel):
    """Producer-side model for the opportunity.identified.v1 data contract."""

    opportunity_id: str = Field(min_length=1)
    watch_intent_id: str = Field(min_length=1)
    event: OpportunityEventDetailsV1
    market_type: MarketType
    selection: str = Field(min_length=1)
    line: float | None
    target_price: int
    best: BestBookPriceV1
    matching: list[BookPriceV1] = Field(min_length=1)


class OpportunityEventContext(DomainModel):
    """What a consumer needs to render an opportunity without a further lookup.

    `best_quoted_at` is the best book's own line-movement time (ADR-009), not the
    ingest time; None means the book does not expose one.
    """

    sport: str | None = None
    league: str | None = None
    home: str | None = None
    away: str | None = None
    starts_at: datetime | None = None
    best_quoted_at: datetime | None = None


def build_opportunity_identified_public_event(
    *,
    opportunity: Opportunity,
    context: OpportunityEventContext,
) -> PublicEvent[OpportunityIdentifiedDataV1]:
    return PublicEvent[OpportunityIdentifiedDataV1](
        id=str(uuid4()),
        type=OPPORTUNITY_IDENTIFIED_V1,
        time=datetime.now(UTC),
        subject=opportunity.id,
        dataschema=_dataschema(OPPORTUNITY_IDENTIFIED_V1),
        data=OpportunityIdentifiedDataV1(
            opportunity_id=opportunity.id,
            watch_intent_id=opportunity.watch_intent_id,
            event=OpportunityEventDetailsV1(
                id=opportunity.event_id,
                sport=context.sport,
                league=context.league,
                home=context.home,
                away=context.away,
                starts_at=context.starts_at,
            ),
            market_type=opportunity.market_type,
            selection=opportunity.selection,
            line=opportunity.line,
            target_price=opportunity.target_price,
            best=BestBookPriceV1(
                sportsbook=opportunity.best_sportsbook,
                price=opportunity.best_price,
                quoted_at=context.best_quoted_at,
            ),
            matching=[
                BookPriceV1(sportsbook=quote.sportsbook, price=quote.price)
                for quote in opportunity.matching_quotes
            ],
        ),
    )


def _dataschema(event_type: str) -> str:
    return f"{_SCHEMA_BASE_URL}/{event_type}.json"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.isoformat()
