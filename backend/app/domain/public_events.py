"""Public events: the versioned contract that leaves the system (ADR-014).

Workflow events are the internal audit trail. A public event is what an outside
reader such as the notifier sees: a CloudEvents 1.0 envelope whose `type` carries
the version, and whose `data` matches a JSON Schema under `contracts/events/`.
Nothing is public by default; each type here is a deliberate choice.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Generic, TypeVar
from uuid import uuid4

from pydantic import Field, PlainSerializer, SerializeAsAny, model_validator

from backend.app.domain.base import DomainModel
from backend.app.domain.models import MarketType, Opportunity

PUBLIC_EVENT_SOURCE = "/oddsengine"
OPPORTUNITY_IDENTIFIED_V1 = "oddsengine.opportunity.identified.v1"
DESTINATION_TEST_V1 = "oddsengine.destination.test.v1"
_SCHEMA_BASE_URL = (
    "https://github.com/mwelch21/OddsExecutionEngine/blob/development/contracts/events"
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.isoformat()


# A timestamp on the wire: ISO 8601 with an offset, a naive value read as UTC.
UtcIso = Annotated[datetime, PlainSerializer(_iso, return_type=str, when_used="json")]

PayloadT = TypeVar("PayloadT", bound=DomainModel, covariant=True)


class PublicEvent(DomainModel, Generic[PayloadT]):
    """A CloudEvents 1.0 envelope, stored whole in the public outbox.

    The payload stays typed until serialization: concrete builders specify their
    payload model, and shared staging ports accept PublicEvent[DomainModel] so new
    event types need no persistence changes. Always parametrize it; a bare
    PublicEvent validates `data` against DomainModel and rejects every field.
    """

    id: str
    type: str
    source: str = PUBLIC_EVENT_SOURCE
    specversion: str = "1.0"
    time: datetime
    subject: str | None = None
    dataschema: str
    data: SerializeAsAny[PayloadT]

    @model_validator(mode="before")
    @classmethod
    def _require_payload_type(cls, values: Any) -> Any:
        # mypy reads a bare PublicEvent as PublicEvent[Any] and lets it through;
        # fail here, at the call site, with the fix in the message, instead of
        # with a ValidationError about every field of `data`.
        if not cls.__pydantic_generic_metadata__["args"]:
            raise TypeError(
                "PublicEvent must be parametrized with its payload model, "
                "e.g. PublicEvent[OpportunityIdentifiedDataV1](...)"
            )
        return values

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
    starts_at: UtcIso | None


class BookPriceV1(DomainModel):
    sportsbook: str = Field(min_length=1)
    price: int


class BestBookPriceV1(BookPriceV1):
    quoted_at: UtcIso | None


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
    expires_at: UtcIso


class DestinationTestDataV1(DomainModel):
    """Producer-side model for the destination.test.v1 data contract."""

    destination_id: str = Field(min_length=1)
    requested_at: UtcIso


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
    valid_for: timedelta,
    context: OpportunityEventContext,
) -> PublicEvent[OpportunityIdentifiedDataV1]:
    """`expires_at` is the boundary the validity engine applies: created_at + TTL.
    Past it, a consumer should drop the event rather than act on it."""
    now = datetime.now(UTC)
    created_at = opportunity.created_at or now
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return PublicEvent[OpportunityIdentifiedDataV1](
        id=str(uuid4()),
        type=OPPORTUNITY_IDENTIFIED_V1,
        time=now,
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
            expires_at=created_at + valid_for,
        ),
    )


def build_destination_test_public_event(
    *, destination_id: str
) -> PublicEvent[DestinationTestDataV1]:
    """A test notification aimed at exactly one destination, named by `subject`.

    It goes through the same outbox, claim and send path as any other event, so a
    test that arrives proves the whole pipeline for that device.
    """
    requested_at = datetime.now(UTC)
    return PublicEvent[DestinationTestDataV1](
        id=str(uuid4()),
        type=DESTINATION_TEST_V1,
        time=requested_at,
        subject=destination_id,
        dataschema=_dataschema(DESTINATION_TEST_V1),
        data=DestinationTestDataV1(
            destination_id=destination_id,
            requested_at=requested_at,
        ),
    )


def _dataschema(event_type: str) -> str:
    return f"{_SCHEMA_BASE_URL}/{event_type}.json"
