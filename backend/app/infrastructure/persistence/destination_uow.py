from uuid import uuid4

from sqlalchemy import RowMapping, insert, select, update
from sqlalchemy.orm import Session

from backend.app.domain.destinations import (
    Channel,
    Destination,
    DisabledReason,
    WebPushKeys,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import destinations_table


class SqlAlchemyDestinationUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyDestinationUnitOfWork":
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

    def get_web_push_destination(self, address: str) -> Destination | None:
        row = (
            self._require_session()
            .execute(
                select(destinations_table).where(
                    destinations_table.c.channel == Channel.WEB_PUSH.value,
                    destinations_table.c.address == address,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _row_to_destination(row)

    def create_web_push_destination(
        self, address: str, keys: WebPushKeys, label: str
    ) -> Destination:
        destination_id = str(uuid4())
        session = self._require_session()
        session.execute(
            insert(destinations_table).values(
                id=destination_id,
                channel=Channel.WEB_PUSH.value,
                label=label,
                address=address,
                config=keys.model_dump(),
            )
        )
        return self._get(destination_id)

    def refresh_web_push_destination(
        self, destination_id: str, keys: WebPushKeys, reactivate: bool
    ) -> Destination:
        values: dict[str, object] = {"config": keys.model_dump()}
        if reactivate:
            values |= {"disabled_at": None, "disabled_reason": None}
        self._require_session().execute(
            update(destinations_table)
            .where(destinations_table.c.id == destination_id)
            .values(**values)
        )
        return self._get(destination_id)

    def list_destinations(self) -> list[Destination]:
        rows = (
            self._require_session()
            .execute(select(destinations_table).order_by(destinations_table.c.created_at))
            .mappings()
            .all()
        )
        return [_row_to_destination(row) for row in rows]

    def _get(self, destination_id: str) -> Destination:
        row = (
            self._require_session()
            .execute(select(destinations_table).where(destinations_table.c.id == destination_id))
            .mappings()
            .one()
        )
        return _row_to_destination(row)

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Destination unit of work must be entered before use.")
        return self._session


def _row_to_destination(row: RowMapping) -> Destination:
    # `config` is deliberately not mapped: channel secrets stay in the database,
    # read only by the notifier.
    return Destination(
        id=row["id"],
        channel=Channel(row["channel"]),
        label=row["label"],
        address=row["address"],
        created_at=row["created_at"],
        last_delivered_at=row["last_delivered_at"],
        disabled_at=row["disabled_at"],
        disabled_reason=(
            None if row["disabled_reason"] is None else DisabledReason(row["disabled_reason"])
        ),
    )
