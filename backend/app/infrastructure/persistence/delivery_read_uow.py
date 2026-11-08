"""Read side of the delivery log (#105).

The select names its columns: a destination's `address` and `config` (the push
endpoint and its keys) are never read here, so they cannot leak into a response.
The event payload is read for its `data` only, which the service turns into a
subject line.
"""

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.domain.deliveries import DeliveryFilter, DeliveryStatus, StoredDelivery
from backend.app.domain.destinations import Channel
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    deliveries_table,
    destinations_table,
    public_events_table,
)

SelectT = TypeVar("SelectT", bound=Select[tuple[Any, ...]])

_JOINED = deliveries_table.join(
    public_events_table, deliveries_table.c.event_id == public_events_table.c.id
).join(destinations_table, deliveries_table.c.destination_id == destinations_table.c.id)


class SqlAlchemyDeliveryReadUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyDeliveryReadUnitOfWork":
        self._session = self._session_factory.create_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        # Read only: release the read transaction, nothing to commit.
        session.rollback()
        session.close()
        self._session = None

    def count_deliveries(self, delivery_filter: DeliveryFilter) -> int:
        query = select(func.count()).select_from(_JOINED)
        return int(
            self._require_session().execute(_apply_filter(query, delivery_filter)).scalar_one()
        )

    def list_deliveries(
        self, delivery_filter: DeliveryFilter, limit: int, offset: int
    ) -> list[StoredDelivery]:
        query = (
            select(
                deliveries_table.c.id,
                deliveries_table.c.event_id,
                public_events_table.c.type.label("event_type"),
                public_events_table.c.payload,
                deliveries_table.c.destination_id,
                destinations_table.c.label.label("destination_label"),
                destinations_table.c.channel,
                deliveries_table.c.status,
                deliveries_table.c.attempts,
                deliveries_table.c.last_error,
                deliveries_table.c.created_at,
                deliveries_table.c.ended_at,
            )
            .select_from(_JOINED)
            # Newest first; `id` breaks ties so paging never repeats or skips a row.
            .order_by(deliveries_table.c.created_at.desc(), deliveries_table.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = self._require_session().execute(_apply_filter(query, delivery_filter)).mappings()
        return [
            StoredDelivery(
                id=row["id"],
                event_id=row["event_id"],
                event_type=row["event_type"],
                event_data=_event_data(row["payload"]),
                destination_id=row["destination_id"],
                destination_label=row["destination_label"],
                channel=Channel(row["channel"]),
                status=DeliveryStatus(row["status"]),
                attempts=row["attempts"],
                last_error=row["last_error"],
                created_at=_as_utc(row["created_at"]),
                ended_at=_as_utc(row["ended_at"]) if row["ended_at"] is not None else None,
            )
            for row in rows
        ]

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Delivery read unit of work must be entered before use.")
        return self._session


def _apply_filter(query: SelectT, delivery_filter: DeliveryFilter) -> SelectT:
    if delivery_filter.status is not None:
        query = query.where(deliveries_table.c.status == delivery_filter.status.value)
    if delivery_filter.event_type is not None:
        query = query.where(public_events_table.c.type == delivery_filter.event_type)
    if delivery_filter.destination_id is not None:
        query = query.where(deliveries_table.c.destination_id == delivery_filter.destination_id)
    return query


def _event_data(payload: Any) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; every time this system stores is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
