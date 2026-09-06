import logging
from uuid import uuid4

from sqlalchemy import insert

from backend.app.application.ports import RecommendationUnitOfWork
from backend.app.domain.models import ExecutionRecommendation, OrderIntent, Quote
from backend.app.infrastructure.persistence.event_staging_uow import (
    SqlAlchemyEventStagingUnitOfWork,
)
from backend.app.infrastructure.persistence.queries import row_to_quote, select_latest_quotes
from backend.app.infrastructure.persistence.schema import (
    execution_recommendations_table,
    order_intents_table,
)


class SqlAlchemyRecommendationUnitOfWork(
    SqlAlchemyEventStagingUnitOfWork,
    RecommendationUnitOfWork,
):
    _logger = logging.getLogger(__name__)
    _log_name = "recommendation_uow"

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
        rows = self._require_session().execute(select_latest_quotes(event_id))
        return [row_to_quote(row) for row in rows.mappings().all()]

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
