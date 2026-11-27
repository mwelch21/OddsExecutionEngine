"""Watch reads and expiry writes shared by the watch and ingestion units of work.

Ingestion expires watches in the same transaction as the status write that
closes their window (ADR-017), so both units of work need the same statements.
"""

from sqlalchemy import RowMapping, select, update
from sqlalchemy.orm import Session

from backend.app.domain.models import (
    ExpiredReason,
    MarketType,
    WatchIntent,
    WatchStatus,
    WatchWindow,
)
from backend.app.infrastructure.persistence.schema import watch_intents_table


def row_to_watch_intent(row: RowMapping) -> WatchIntent:
    reason = row["expired_reason"]
    return WatchIntent(
        id=row["id"],
        event_id=row["event_external_id"],
        market_type=MarketType(row["market_type"]),
        selection=row["selection"],
        target_price=row["target_price"],
        window=WatchWindow(row["watch_window"]),
        line=row["line"],
        expires_at=row["expires_at"],
        status=WatchStatus(row["status"]),
        expired_reason=None if reason is None else ExpiredReason(reason),
        created_at=row["created_at"],
    )


def list_active_watch_intents(
    session: Session, event_ids: list[str] | None = None
) -> list[WatchIntent]:
    """Stored-active watches, on the given events when named."""
    query = select(watch_intents_table).where(
        watch_intents_table.c.status == WatchStatus.ACTIVE.value
    )
    if event_ids is not None:
        if not event_ids:
            return []
        query = query.where(watch_intents_table.c.event_external_id.in_(event_ids))
    rows = session.execute(query).mappings().all()
    return [row_to_watch_intent(row) for row in rows]


def expire_watch_intents(
    session: Session, reasons: dict[str, ExpiredReason]
) -> list[WatchIntent]:
    """Expire each still-active watch with its reason; return the ones expired.

    Only active rows change, so a watch another transaction just triggered or
    cancelled keeps that terminal status.
    """
    if not reasons:
        return []
    expired_ids: list[str] = []
    for reason in sorted(set(reasons.values())):
        ids = sorted(watch_id for watch_id, r in reasons.items() if r is reason)
        changed = session.execute(
            update(watch_intents_table)
            .where(
                watch_intents_table.c.id.in_(ids),
                watch_intents_table.c.status == WatchStatus.ACTIVE.value,
            )
            .values(status=WatchStatus.EXPIRED.value, expired_reason=reason.value)
            .returning(watch_intents_table.c.id)
        )
        expired_ids.extend(str(watch_id) for watch_id in changed.scalars())
    if not expired_ids:
        return []
    rows = (
        session.execute(
            select(watch_intents_table)
            .where(watch_intents_table.c.id.in_(expired_ids))
            .order_by(watch_intents_table.c.created_at, watch_intents_table.c.id)
        )
        .mappings()
        .all()
    )
    return [row_to_watch_intent(row) for row in rows]
