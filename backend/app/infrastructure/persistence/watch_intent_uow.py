import logging
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import RowMapping, Select, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.app.domain.events import WorkflowEvent
from backend.app.domain.models import (
    MarketType,
    MatchingQuote,
    Opportunity,
    Quote,
    WatchIntent,
    WatchStatus,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    events_table,
    market_quotes_latest_table,
    markets_table,
    opportunities_table,
    watch_intents_table,
    workflow_events_table,
)


class SqlAlchemyWatchIntentUnitOfWork:
    _logger = logging.getLogger(__name__)

    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._staged_events: list[WorkflowEvent] = []
        self._committed_events: tuple[WorkflowEvent, ...] = ()

    def __enter__(self) -> "SqlAlchemyWatchIntentUnitOfWork":
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
                    "watch_intent_uow.committed",
                    extra={
                        "workflow_id": (
                            self._committed_events[0].workflow_id
                            if self._committed_events
                            else "-"
                        ),
                        "event_count": len(self._committed_events),
                    },
                )
            else:
                session.rollback()
                self._committed_events = ()
                self._logger.warning("watch_intent_uow.rolled_back")
        finally:
            self._staged_events = []
            session.close()
            self._session = None

    def create_watch_intent(
        self,
        event_id: str,
        market_type: MarketType,
        selection: str,
        target_price: int,
        line: float | None,
        expires_at: datetime | None = None,
    ) -> WatchIntent:
        watch_intent_id = str(uuid4())
        session = self._require_session()
        session.execute(
            insert(watch_intents_table).values(
                id=watch_intent_id,
                event_external_id=event_id,
                market_type=market_type.value,
                selection=selection,
                line=line,
                target_price=target_price,
                expires_at=expires_at,
                status=WatchStatus.ACTIVE.value,
            )
        )
        # Read back to get server-generated created_at
        row = session.execute(
            select(watch_intents_table).where(watch_intents_table.c.id == watch_intent_id)
        ).mappings().one()
        return _row_to_watch_intent(row)

    def cancel_watch_intent(self, watch_intent_id: str) -> WatchIntent:
        session = self._require_session()
        session.execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id == watch_intent_id)
            .values(status=WatchStatus.CANCELLED.value)
        )
        row = session.execute(
            select(watch_intents_table).where(watch_intents_table.c.id == watch_intent_id)
        ).mappings().one_or_none()
        if row is None:
            raise ValueError(f"Watch intent {watch_intent_id} not found")
        return _row_to_watch_intent(row)

    def list_active_watch_intents(
        self, event_id: str | None = None
    ) -> list[WatchIntent]:
        query = select(watch_intents_table).where(
            watch_intents_table.c.status == WatchStatus.ACTIVE.value
        )
        if event_id is not None:
            query = query.where(watch_intents_table.c.event_external_id == event_id)
        rows = self._require_session().execute(query).mappings().all()
        return [_row_to_watch_intent(row) for row in rows]

    def list_watch_intents(
        self,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        query = select(watch_intents_table)
        if event_id is not None:
            query = query.where(watch_intents_table.c.event_external_id == event_id)
        if status is not None:
            query = query.where(watch_intents_table.c.status == status.value)
        rows = (
            self._require_session()
            .execute(query.order_by(watch_intents_table.c.created_at))
            .mappings()
            .all()
        )
        return [_row_to_watch_intent(row) for row in rows]

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None:
        row = (
            self._require_session()
            .execute(
                select(watch_intents_table).where(
                    watch_intents_table.c.id == watch_intent_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _row_to_watch_intent(row)

    def expire_watch_intents(self, watch_intent_ids: list[str]) -> list[WatchIntent]:
        if not watch_intent_ids:
            return []

        session = self._require_session()
        session.execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id.in_(watch_intent_ids))
            .values(status=WatchStatus.EXPIRED.value)
        )
        rows = (
            session.execute(
                select(watch_intents_table).where(
                    watch_intents_table.c.id.in_(watch_intent_ids)
                )
            )
            .mappings()
            .all()
        )
        return [_row_to_watch_intent(row) for row in rows]

    def trigger_watch_intents(self, watch_intent_ids: list[str]) -> list[WatchIntent]:
        """Retire watches that produced an opportunity. Terminal: they never re-arm."""
        if not watch_intent_ids:
            return []

        session = self._require_session()
        session.execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id.in_(watch_intent_ids))
            .values(status=WatchStatus.TRIGGERED.value)
        )
        rows = (
            session.execute(
                select(watch_intents_table).where(
                    watch_intents_table.c.id.in_(watch_intent_ids)
                )
            )
            .mappings()
            .all()
        )
        return [_row_to_watch_intent(row) for row in rows]

    def list_quotes(self, event_id: str) -> list[Quote]:
        rows = self._require_session().execute(
            select(
                events_table.c.external_id.label("event_id"),
                market_quotes_latest_table.c.sportsbook,
                markets_table.c.market_type,
                markets_table.c.selection,
                market_quotes_latest_table.c.price,
                markets_table.c.line,
            )
            .select_from(
                market_quotes_latest_table.join(
                    markets_table,
                    market_quotes_latest_table.c.market_id == markets_table.c.id,
                ).join(events_table, markets_table.c.event_id == events_table.c.id)
            )
            .where(events_table.c.external_id == event_id)
        )
        return [_row_to_quote(row) for row in rows.mappings().all()]

    def get_market_id_lookup(
        self, event_id: str
    ) -> dict[tuple[str, str, str, float | None], str]:
        rows = self._require_session().execute(
            select(
                markets_table.c.id,
                events_table.c.external_id.label("event_id"),
                markets_table.c.market_type,
                markets_table.c.selection,
                markets_table.c.line,
            )
            .select_from(
                markets_table.join(
                    events_table, markets_table.c.event_id == events_table.c.id
                )
            )
            .where(events_table.c.external_id == event_id)
        ).mappings().all()
        return {
            (row["event_id"], row["market_type"], row["selection"], row["line"]): row["id"]
            for row in rows
        }

    def create_opportunities(
        self, opportunities: list[Opportunity]
    ) -> list[Opportunity]:
        if not opportunities:
            return []
        session = self._require_session()
        inserted_opportunities: list[Opportunity] = []
        dialect_name = _dialect_name(session)
        for opp in opportunities:
            inserted_id = cast(
                str | None,
                session.execute(
                    _build_opportunity_insert_statement(
                        dialect_name=dialect_name,
                        opportunity=opp,
                    )
                ).scalar_one_or_none(),
            )
            if inserted_id is not None:
                inserted_opportunities.append(opp)
        return inserted_opportunities

    def _opportunity_query(self) -> Select[tuple[object, ...]]:
        return select(
            opportunities_table,
            watch_intents_table.c.market_type,
            watch_intents_table.c.selection,
            watch_intents_table.c.target_price,
            watch_intents_table.c.line,
        ).select_from(
            opportunities_table.join(
                watch_intents_table,
                opportunities_table.c.watch_intent_id == watch_intents_table.c.id,
            )
        )

    def list_opportunities(
        self, event_id: str | None = None
    ) -> list[Opportunity]:
        query = self._opportunity_query()
        if event_id is not None:
            query = query.where(
                opportunities_table.c.event_external_id == event_id
            )
        rows = self._require_session().execute(query).mappings().all()
        return [_row_to_opportunity(row) for row in rows]

    def get_opportunity(self, opportunity_id: str) -> Opportunity | None:
        row = (
            self._require_session()
            .execute(
                self._opportunity_query().where(
                    opportunities_table.c.id == opportunity_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _row_to_opportunity(row)

    def get_latest_quote_times(
        self, opportunities: list[Opportunity]
    ) -> list[tuple[Opportunity, datetime | None]]:
        """Quote time per opportunity, read from the best book only.

        Staleness means the headline price moved or vanished. A non-best book
        changing is irrelevant — the reader was never going to use it.
        """
        result: list[tuple[Opportunity, datetime | None]] = []
        session = self._require_session()
        for opp in opportunities:
            row = session.execute(
                select(market_quotes_latest_table.c.quoted_at).where(
                    market_quotes_latest_table.c.market_id == opp.market_id,
                    market_quotes_latest_table.c.sportsbook == opp.best_sportsbook,
                )
            ).scalar_one_or_none()
            result.append((opp, row))
        return result

    def get_event_starts_at(self, event_external_id: str) -> datetime | None:
        return self._require_session().execute(
            select(events_table.c.starts_at).where(
                events_table.c.external_id == event_external_id
            )
        ).scalar_one_or_none()

    def stage_event(self, event: WorkflowEvent) -> None:
        self._staged_events.append(event)

    @property
    def committed_events(self) -> tuple[WorkflowEvent, ...]:
        return self._committed_events

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Watch intent unit of work must be entered before use.")
        return self._session

    def _persist_staged_events(self) -> None:
        if not self._staged_events:
            return

        self._logger.info(
            "watch_intent_uow.persisting_events",
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


def _row_to_watch_intent(row: RowMapping) -> WatchIntent:
    return WatchIntent(
        id=row["id"],
        event_id=row["event_external_id"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        target_price=row["target_price"],
        line=row["line"],
        expires_at=row["expires_at"],
        status=WatchStatus(row["status"]),
        created_at=row["created_at"],
    )


def _row_to_quote(row: RowMapping) -> Quote:
    return Quote(
        event_id=row["event_id"],
        sportsbook=row["sportsbook"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        price=row["price"],
        line=row["line"],
    )


def _row_to_opportunity(row: RowMapping) -> Opportunity:
    return Opportunity(
        id=row["id"],
        watch_intent_id=row["watch_intent_id"],
        event_id=row["event_external_id"],
        market_id=row["market_id"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        target_price=row["target_price"],
        best_sportsbook=row["best_sportsbook"],
        best_price=row["best_price"],
        matching_quotes=[
            MatchingQuote(sportsbook=quote["sportsbook"], price=quote["price"])
            for quote in row["matching_quotes"]
        ],
        line=row["line"],
        created_at=row["created_at"],
    )


def _dialect_name(session: Session) -> str:
    if session.bind is None:
        raise RuntimeError("Watch intent unit of work session is not bound to an engine.")
    return session.bind.dialect.name


def _build_opportunity_insert_statement(
    *,
    dialect_name: str,
    opportunity: Opportunity,
) -> Any:
    values = {
        "id": opportunity.id,
        "watch_intent_id": opportunity.watch_intent_id,
        "event_external_id": opportunity.event_id,
        "market_id": opportunity.market_id,
        "best_sportsbook": opportunity.best_sportsbook,
        "best_price": opportunity.best_price,
        "matching_quotes": [
            quote.model_dump(mode="json") for quote in opportunity.matching_quotes
        ],
    }
    conflict_columns = ["watch_intent_id"]

    if dialect_name == "postgresql":
        return postgresql_insert(opportunities_table).values(
            **values
        ).on_conflict_do_nothing(index_elements=conflict_columns).returning(
            opportunities_table.c.id
        )

    if dialect_name == "sqlite":
        return sqlite_insert(opportunities_table).values(
            **values
        ).on_conflict_do_nothing(index_elements=conflict_columns).returning(
            opportunities_table.c.id
        )

    raise RuntimeError(f"Unsupported dialect for opportunity insert: {dialect_name}")
