from uuid import uuid4

from sqlalchemy import RowMapping, insert, select
from sqlalchemy.orm import Session

from backend.app.application.ports import RecommendationUnitOfWork
from backend.app.domain.models import ExecutionRecommendation, MarketType, OrderIntent, Quote
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    events_table,
    execution_recommendations_table,
    market_quotes_latest_table,
    markets_table,
    order_intents_table,
)


class SqlAlchemyRecommendationUnitOfWork(RecommendationUnitOfWork):
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyRecommendationUnitOfWork":
        self._session = self._session_factory.create_session()
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
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
            self._session = None

    def create_order_intent(self, intent: OrderIntent) -> str:
        order_intent_id = str(uuid4())
        self._require_session().execute(
            insert(order_intents_table).values(
                id=order_intent_id,
                event_external_id=intent.event_id,
                market_type=intent.market_type.value,
                selection=intent.selection,
                line=intent.line,
                target_price=intent.target_price,
            )
        )
        return order_intent_id

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

    def create_execution_recommendation(
        self,
        order_intent_id: str,
        recommendation: ExecutionRecommendation,
    ) -> str:
        recommendation_id = str(uuid4())
        self._require_session().execute(
            insert(execution_recommendations_table).values(
                id=recommendation_id,
                order_intent_id=order_intent_id,
                fillable=recommendation.fillable,
                matched_quote_count=recommendation.matched_quote_count,
                best_quote=_quote_payload(recommendation.best_quote),
                nearest_miss=_quote_payload(recommendation.nearest_miss),
                ranked_quotes=[_quote_payload(quote) for quote in recommendation.ranked_quotes],
            )
        )
        return recommendation_id

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Recommendation unit of work must be entered before use.")
        return self._session


def _row_to_quote(row: RowMapping) -> Quote:
    return Quote(
        event_id=row["event_id"],
        sportsbook=row["sportsbook"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        price=row["price"],
        line=row["line"],
    )


def _quote_payload(quote: Quote | None) -> dict[str, object] | None:
    if quote is None:
        return None

    return {
        "event_id": quote.event_id,
        "sportsbook": quote.sportsbook,
        "market_type": quote.market_type.value,
        "selection": quote.selection,
        "price": quote.price,
        "line": quote.line,
    }
