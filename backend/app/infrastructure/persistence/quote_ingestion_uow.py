import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import CursorResult, Row, RowMapping, delete, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.application.ports import QuoteIngestionUnitOfWork
from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    EventObservation,
    EventSport,
    EventStatus,
    LinePhase,
    PersistedQuote,
    Quote,
    QuoteRefreshPersistenceResult,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.market_identity import build_line_key
from backend.app.infrastructure.persistence.schema import (
    event_participants_table,
    events_table,
    market_quotes_history_table,
    market_quotes_latest_table,
    markets_table,
    sport_refreshes_table,
    workflow_events_table,
)
from backend.app.infrastructure.persistence.upsert import upsert


class SqlAlchemyQuoteIngestionUnitOfWork(QuoteIngestionUnitOfWork):
    _logger = logging.getLogger(__name__)

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "SqlAlchemyQuoteIngestionUnitOfWork":
        self._session = self._session_factory.create_session()
        self._staged_events = []
        self._committed_events = ()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is None:
                self._persist_staged_events()
                session.commit()
                self._committed_events = tuple(self._staged_events)
                self._logger.info(
                    "quote_ingestion_uow.committed",
                    extra={
                        "workflow_id": (
                            self._committed_events[0].workflow_id if self._committed_events else "-"
                        ),
                        "event_count": len(self._committed_events),
                    },
                )
            else:
                session.rollback()
                self._committed_events = ()
                self._logger.warning("quote_ingestion_uow.rolled_back")
        finally:
            self._staged_events = []
            session.close()
            self._session = None

    def persist_quotes(
        self,
        event_id: str,
        quotes: list[Quote],
        event_metadata: dict[str, object] | None = None,
        observation: EventObservation | None = None,
    ) -> QuoteRefreshPersistenceResult:
        session = self._require_session()
        ingested_at = datetime.now(UTC)
        event_row_id = self._ensure_event(event_id, event_metadata)
        if observation is not None:
            self._write_observation(event_row_id, observation)
        persisted_quotes: list[PersistedQuote] = []
        created_market_count = 0

        for quote in quotes:
            phase = quote.phase or LinePhase.PRE_GAME
            market_id, market_created = self._ensure_market(event_row_id, quote)
            if market_created:
                created_market_count += 1

            session.execute(
                delete(market_quotes_latest_table).where(
                    market_quotes_latest_table.c.market_id == market_id,
                    market_quotes_latest_table.c.sportsbook == quote.sportsbook,
                )
            )
            session.execute(
                insert(market_quotes_latest_table).values(
                    market_id=market_id,
                    sportsbook=quote.sportsbook,
                    price=quote.price,
                    ingested_at=ingested_at,
                    quoted_at=quote.quoted_at,
                    phase=phase.value,
                )
            )
            session.execute(
                insert(market_quotes_history_table).values(
                    id=str(uuid4()),
                    market_id=market_id,
                    sportsbook=quote.sportsbook,
                    price=quote.price,
                    ingested_at=ingested_at,
                    quoted_at=quote.quoted_at,
                    phase=phase.value,
                )
            )
            persisted_quotes.append(
                PersistedQuote(
                    quote=quote.model_copy(
                        update={"ingested_at": ingested_at, "phase": phase}
                    ),
                    market_id=market_id,
                    market_created=market_created,
                )
            )

        return QuoteRefreshPersistenceResult(
            event_id=event_id,
            persisted_quotes=persisted_quotes,
            created_market_count=created_market_count,
            updated_latest_count=len(persisted_quotes),
            appended_history_count=len(persisted_quotes),
        )

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Quote ingestion unit of work must be entered before use.")
        return self._session

    def get_event_sport(self, event_id: str) -> EventSport | None:
        """The stored sport and league for an event, or None if it was never stored."""
        row = (
            self._require_session()
            .execute(
                select(events_table.c.sport, events_table.c.league).where(
                    events_table.c.external_id == event_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return EventSport(sport=row["sport"], league=row["league"])

    def get_event_starts_at(self, event_id: str) -> datetime | None:
        value = (
            self._require_session()
            .execute(select(events_table.c.starts_at).where(events_table.c.external_id == event_id))
            .scalar_one_or_none()
        )
        return _as_utc(value)

    def list_unended_event_starts(
        self, sport: str, league: str | None
    ) -> dict[str, datetime | None]:
        rows = self._require_session().execute(
            select(events_table.c.external_id, events_table.c.starts_at).where(
                events_table.c.sport == sport,
                events_table.c.league.is_(None)
                if league is None
                else events_table.c.league == league,
                events_table.c.status != EventStatus.ENDED.value,
            )
        )
        return {str(row.external_id): _as_utc(row.starts_at) for row in rows}

    def set_event_status(
        self, event_ids: list[str], status: EventStatus, observed_at: datetime
    ) -> None:
        if not event_ids:
            return
        self._require_session().execute(
            update(events_table)
            .where(events_table.c.external_id.in_(event_ids), _not_newer_than(observed_at))
            .values(status=status.value, status_observed_at=observed_at)
        )

    def _write_observation(self, event_row_id: str, observation: EventObservation) -> None:
        values: dict[str, object] = {
            "status": observation.status.value,
            "status_observed_at": observation.observed_at,
        }
        if observation.starts_at is not None:
            values["starts_at"] = observation.starts_at
        result = cast(
            CursorResult[Any],
            self._require_session().execute(
                update(events_table)
                .where(
                    events_table.c.id == event_row_id,
                    _not_newer_than(observation.observed_at),
                )
                .values(**values)
            ),
        )
        if result.rowcount == 0:
            self._logger.info(
                "quote_ingestion_uow.stale_observation_skipped",
                extra={"event_row_id": event_row_id, "status": observation.status.value},
            )

    def record_sport_refreshed(self, sport_key: str, refreshed_at: datetime) -> None:
        """Stamp a sport-wide pull; the Auto-Refresh cooldown runs from here."""
        upsert(
            self._require_session(),
            sport_refreshes_table,
            {"sport_key": sport_key, "last_refreshed_at": refreshed_at},
            key_columns=["sport_key"],
        )

    def _ensure_event(
        self,
        external_event_id: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        session = self._require_session()
        event_metadata = dict(metadata) if metadata else {}
        participants = cast(
            list[dict[str, object]],
            event_metadata.pop("participants", []),
        )

        row = session.execute(
            select(events_table.c.id).where(events_table.c.external_id == external_event_id)
        ).first()
        if row is not None:
            row_id = _row_value(row, "id")
            if event_metadata:
                session.execute(
                    update(events_table)
                    .where(events_table.c.id == row_id)
                    .values(**event_metadata)
                )
            if participants:
                self._upsert_participants(row_id, participants)
            return row_id

        event_row_id = str(uuid4())
        values: dict[str, object] = {
            "id": event_row_id,
            "external_id": external_event_id,
        }
        if event_metadata:
            values.update(event_metadata)
        session.execute(insert(events_table).values(**values))
        if participants:
            self._upsert_participants(event_row_id, participants)
        return event_row_id

    def _upsert_participants(
        self, event_row_id: str, participants: list[dict[str, object]]
    ) -> None:
        session = self._require_session()
        session.execute(
            delete(event_participants_table).where(
                event_participants_table.c.event_id == event_row_id
            )
        )
        for p in participants:
            session.execute(
                insert(event_participants_table).values(
                    id=str(uuid4()),
                    event_id=event_row_id,
                    participant_name=p["participant_name"],
                    role=p["role"],
                    side=p.get("side"),
                    sort_order=p.get("sort_order", 0),
                )
            )

    def _ensure_market(self, event_row_id: str, quote: Quote) -> tuple[str, bool]:
        session = self._require_session()
        line_key = build_line_key(quote.line)
        row = session.execute(
            select(markets_table.c.id).where(
                markets_table.c.event_id == event_row_id,
                markets_table.c.market_type == quote.market_type.value,
                markets_table.c.selection == quote.selection,
                markets_table.c.line_key == line_key,
            )
        ).first()
        if row is not None:
            return _row_value(row, "id"), False

        market_id = str(uuid4())
        session.execute(
            insert(markets_table).values(
                id=market_id,
                event_id=event_row_id,
                market_type=quote.market_type.value,
                selection=quote.selection,
                line=quote.line,
                line_key=line_key,
            )
        )
        return market_id, True

    def _persist_staged_events(self) -> None:
        if not self._staged_events:
            return

        self._logger.info(
            "quote_ingestion_uow.persisting_events",
            extra={
                "workflow_id": self._staged_events[0].workflow_id,
                "event_count": len(self._staged_events),
            },
        )
        self._require_session().execute(
            insert(workflow_events_table),
            [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "workflow_id": event.workflow_id,
                    "payload": event.payload.model_dump(mode="json"),
                    "occurred_at": event.occurred_at,
                }
                for event in self._staged_events
            ],
        )


def _not_newer_than(observed_at: datetime) -> ColumnElement[bool]:
    """The stored observation is absent or no newer than this one."""
    return events_table.c.status_observed_at.is_(None) | (
        events_table.c.status_observed_at <= observed_at
    )


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; every time this system stores is UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _row_value(row: Row[tuple[object]] | RowMapping | tuple[str], key: str) -> str:
    if isinstance(row, Row):
        return str(row._mapping[key])
    if isinstance(row, RowMapping):
        return str(row[key])
    return row[0]
