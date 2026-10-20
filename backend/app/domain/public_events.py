"""Public events: the versioned contract that leaves the system (ADR-014).

Workflow events are the internal audit trail. A public event is what an outside
reader such as the notifier sees: a CloudEvents 1.0 envelope whose `type` carries
the version, and whose `data` matches a JSON Schema under `contracts/events/`.
Nothing is public by default; each type here is a deliberate choice.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.domain.base import DomainModel
from backend.app.domain.models import Opportunity

PUBLIC_EVENT_SOURCE = "/oddsengine"
OPPORTUNITY_IDENTIFIED_V1 = "oddsengine.opportunity.identified.v1"
_SCHEMA_BASE_URL = (
    "https://github.com/mwelch21/OddsExecutionEngine/blob/development/contracts/events"
)


class PublicEvent(DomainModel):
    """A CloudEvents 1.0 envelope, stored whole in the public outbox."""

    id: str
    type: str
    source: str = PUBLIC_EVENT_SOURCE
    specversion: str = "1.0"
    time: datetime
    subject: str | None = None
    dataschema: str
    data: dict[str, Any]

    def to_cloudevent(self) -> dict[str, Any]:
        """The structured-mode JSON form. Unset optional attributes are absent, not null;
        nulls inside `data` are kept, because the schema defines them."""
        envelope = self.model_dump(mode="json")
        if envelope["subject"] is None:
            del envelope["subject"]
        return envelope


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
) -> PublicEvent:
    return PublicEvent(
        id=str(uuid4()),
        type=OPPORTUNITY_IDENTIFIED_V1,
        time=datetime.now(UTC),
        subject=opportunity.id,
        dataschema=_dataschema(OPPORTUNITY_IDENTIFIED_V1),
        data={
            "opportunity_id": opportunity.id,
            "watch_intent_id": opportunity.watch_intent_id,
            "event": {
                "id": opportunity.event_id,
                "sport": context.sport,
                "league": context.league,
                "home": context.home,
                "away": context.away,
                "starts_at": _iso(context.starts_at),
            },
            "market_type": opportunity.market_type.value,
            "selection": opportunity.selection,
            "line": opportunity.line,
            "target_price": opportunity.target_price,
            "best": {
                "sportsbook": opportunity.best_sportsbook,
                "price": opportunity.best_price,
                "quoted_at": _iso(context.best_quoted_at),
            },
            "matching": [
                {"sportsbook": quote.sportsbook, "price": quote.price}
                for quote in opportunity.matching_quotes
            ],
        },
    )


def _dataschema(event_type: str) -> str:
    return f"{_SCHEMA_BASE_URL}/{event_type}.json"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.isoformat()
