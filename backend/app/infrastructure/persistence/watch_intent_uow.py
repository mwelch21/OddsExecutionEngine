import logging

from sqlalchemy import insert, select, update

from backend.app.application.ports import WatchIntentUnitOfWork
from backend.app.domain.models import WatchIntent, WatchStatus
from backend.app.infrastructure.persistence.event_staging_uow import (
    SqlAlchemyEventStagingUnitOfWork,
)
from backend.app.infrastructure.persistence.queries import row_to_watch_intent
from backend.app.infrastructure.persistence.schema import (
    watch_intents_table,
)


class SqlAlchemyWatchIntentUnitOfWork(
    SqlAlchemyEventStagingUnitOfWork,
    WatchIntentUnitOfWork,
):
    _logger = logging.getLogger(__name__)
    _log_name = "watch_intent_uow"

    def create_watch_intent(self, watch_intent: WatchIntent) -> None:
        self._require_session().execute(
            insert(watch_intents_table).values(
                id=watch_intent.id,
                event_external_id=watch_intent.event_id,
                market_type=watch_intent.market_type.value,
                selection=watch_intent.selection,
                line=watch_intent.line,
                target_price=watch_intent.target_price,
                expires_at=watch_intent.expires_at,
                status=watch_intent.status.value,
                created_at=watch_intent.created_at,
            )
        )

    def list_watch_intents(
        self,
        *,
        event_id: str | None = None,
        status: WatchStatus | None = None,
    ) -> list[WatchIntent]:
        statement = select(watch_intents_table).order_by(watch_intents_table.c.created_at)
        if event_id is not None:
            statement = statement.where(watch_intents_table.c.event_external_id == event_id)
        if status is not None:
            statement = statement.where(watch_intents_table.c.status == status.value)

        rows = self._require_session().execute(statement).mappings().all()
        return [row_to_watch_intent(row) for row in rows]

    def get_watch_intent(self, watch_intent_id: str) -> WatchIntent | None:
        row = (
            self._require_session()
            .execute(select(watch_intents_table).where(watch_intents_table.c.id == watch_intent_id))
            .mappings()
            .first()
        )
        return None if row is None else row_to_watch_intent(row)

    def update_watch_intent_status(self, watch_intent_id: str, status: WatchStatus) -> None:
        self._require_session().execute(
            update(watch_intents_table)
            .where(watch_intents_table.c.id == watch_intent_id)
            .values(status=status.value)
        )
