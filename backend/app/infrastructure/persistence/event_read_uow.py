"""Read side of the event browse list.

Filtering and paging happen in SQL, not in Python. A page whose "started" events
were dropped after the fact would report a total the rows do not add up to, and
"page 2 of 7" is the one thing this endpoint exists to make renderable.
"""

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import RowMapping, Select, case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.domain.models import (
    EventFilter,
    EventParticipant,
    EventQuoteFreshness,
    EventSummary,
    MarketQuotes,
    MarketType,
    Quote,
)
from backend.app.infrastructure.persistence.database import DatabaseSessionFactory
from backend.app.infrastructure.persistence.schema import (
    event_participants_table,
    events_table,
    market_quotes_latest_table,
    markets_table,
)

SelectT = TypeVar("SelectT", bound=Select[tuple[Any, ...]])


class SqlAlchemyEventReadUnitOfWork:
    def __init__(self, session_factory: DatabaseSessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyEventReadUnitOfWork":
        self._session = self._session_factory.create_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        session = self._require_session()
        # Nothing here writes, so there is nothing to commit — only the read
        # transaction to release.
        session.rollback()
        session.close()
        self._session = None

    def count_events(self, event_filter: EventFilter, now: datetime) -> int:
        query = select(func.count()).select_from(events_table)
        return int(
            self._require_session()
            .execute(_apply_filter(query, event_filter, now))
            .scalar_one()
        )

    def list_events(
        self,
        event_filter: EventFilter,
        now: datetime,
        limit: int,
        offset: int,
    ) -> list[EventSummary]:
        session = self._require_session()
        query = (
            select(
                events_table.c.id,
                events_table.c.external_id,
                events_table.c.sport,
                events_table.c.league,
                events_table.c.status,
                events_table.c.starts_at,
            )
            # Soonest first. `external_id` breaks ties so paging never repeats or
            # skips a row, and NULL start times sort last on every backend rather
            # than leading on SQLite and trailing on Postgres.
            .order_by(
                events_table.c.starts_at.asc().nullslast(),
                events_table.c.external_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = (
            session.execute(_apply_filter(query, event_filter, now)).mappings().all()
        )
        return self._summaries(session, list(rows))

    def get_event(self, event_id: str) -> EventSummary | None:
        """One event by its external id, carrying the same header the list shows.

        No started-event filter: the browse list hides started events because
        they cannot be filled, but asking for one by id is a different question
        and its board still renders.
        """
        session = self._require_session()
        rows = (
            session.execute(
                select(
                    events_table.c.id,
                    events_table.c.external_id,
                    events_table.c.sport,
                    events_table.c.league,
                    events_table.c.status,
                    events_table.c.starts_at,
                ).where(events_table.c.external_id == event_id)
            )
            .mappings()
            .all()
        )
        summaries = self._summaries(session, list(rows))
        return summaries[0] if summaries else None

    def list_market_quotes(self, event_id: str) -> list[MarketQuotes]:
        """Every market of one event with the books quoting it, unranked.

        Outer-joined, so a market no book is currently quoting comes back empty
        rather than vanishing — "nobody is offering this" is an answer the board
        has to be able to show.
        """
        session = self._require_session()
        rows = (
            session.execute(
                select(
                    markets_table.c.id.label("market_id"),
                    markets_table.c.market_type,
                    markets_table.c.selection,
                    markets_table.c.line,
                    market_quotes_latest_table.c.sportsbook,
                    market_quotes_latest_table.c.price,
                    market_quotes_latest_table.c.quoted_at,
                    market_quotes_latest_table.c.ingested_at,
                )
                .select_from(
                    markets_table.join(
                        events_table, markets_table.c.event_id == events_table.c.id
                    ).outerjoin(
                        market_quotes_latest_table,
                        market_quotes_latest_table.c.market_id == markets_table.c.id,
                    )
                )
                .where(events_table.c.external_id == event_id)
                # Markets group by type, then by line, then by selection, so the
                # board reads the same way on every backend and on every request.
                .order_by(
                    markets_table.c.market_type.asc(),
                    markets_table.c.line.asc().nullslast(),
                    markets_table.c.selection.asc(),
                )
            )
            .mappings()
            .all()
        )

        markets: dict[str, MarketQuotes] = {}
        for row in rows:
            market = markets.setdefault(
                str(row["market_id"]),
                MarketQuotes(
                    market_type=MarketType(row["market_type"]),
                    selection=row["selection"],
                    line=row["line"],
                    quotes=[],
                ),
            )
            if row["sportsbook"] is None:
                continue
            market.quotes.append(
                Quote(
                    event_id=event_id,
                    sportsbook=row["sportsbook"],
                    market_type=market.market_type,
                    selection=market.selection,
                    price=row["price"],
                    line=market.line,
                    quoted_at=_as_utc(row["quoted_at"]),
                    ingested_at=_as_utc(row["ingested_at"]),
                )
            )
        return list(markets.values())

    def _summaries(
        self, session: Session, rows: list[RowMapping]
    ) -> list[EventSummary]:
        if not rows:
            return []

        row_ids = [str(row["id"]) for row in rows]
        participants = self._participants_by_event(session, row_ids)
        freshness = self._freshness_by_event(session, row_ids)

        return [
            EventSummary(
                id=str(row["external_id"]),
                sport=row["sport"],
                league=row["league"],
                status=row["status"],
                starts_at=_as_utc(row["starts_at"]),
                participants=participants.get(str(row["id"]), []),
                quotes=freshness.get(str(row["id"]), EventQuoteFreshness()),
            )
            for row in rows
        ]

    def _participants_by_event(
        self, session: Session, event_row_ids: list[str]
    ) -> dict[str, list[EventParticipant]]:
        rows = (
            session.execute(
                select(event_participants_table)
                .where(event_participants_table.c.event_id.in_(event_row_ids))
                .order_by(
                    event_participants_table.c.event_id,
                    event_participants_table.c.sort_order,
                )
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[EventParticipant]] = {}
        for row in rows:
            grouped.setdefault(str(row["event_id"]), []).append(
                EventParticipant(
                    name=row["participant_name"],
                    role=row["role"],
                    side=row["side"],
                    sort_order=row["sort_order"],
                )
            )
        return grouped

    def _freshness_by_event(
        self, session: Session, event_row_ids: list[str]
    ) -> dict[str, EventQuoteFreshness]:
        """One aggregate per event over its latest quotes.

        `MIN(quoted_at)` ignores NULLs by definition, which is exactly right here:
        a book with no line-movement time contributes to the unknown count, never
        to the reported age. Events with no quotes produce no row at all and keep
        the all-None default rather than being invented as age zero.

        Book counts are `COUNT(DISTINCT sportsbook)`, not row counts. One book
        quoting both sides of three markets is six rows and still one book, so
        counting rows would report six unknown-age "books" for a single silent
        provider.
        """
        book_count: ColumnElement[int] = func.count(
            market_quotes_latest_table.c.sportsbook.distinct()
        )
        unknown_line_age: ColumnElement[int] = func.count(
            case(
                (
                    market_quotes_latest_table.c.quoted_at.is_(None),
                    market_quotes_latest_table.c.sportsbook,
                )
            ).distinct()
        )
        rows = (
            session.execute(
                select(
                    markets_table.c.event_id,
                    func.count().label("quote_count"),
                    func.max(market_quotes_latest_table.c.ingested_at).label(
                        "last_ingested_at"
                    ),
                    func.min(market_quotes_latest_table.c.quoted_at).label(
                        "oldest_line_quoted_at"
                    ),
                    book_count.label("book_count"),
                    unknown_line_age.label("books_with_unknown_line_age"),
                )
                .select_from(
                    market_quotes_latest_table.join(
                        markets_table,
                        market_quotes_latest_table.c.market_id == markets_table.c.id,
                    )
                )
                .where(markets_table.c.event_id.in_(event_row_ids))
                .group_by(markets_table.c.event_id)
            )
            .mappings()
            .all()
        )
        return {str(row["event_id"]): _row_to_freshness(row) for row in rows}

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Event read unit of work must be entered before use.")
        return self._session


def _apply_filter(
    query: SelectT,
    event_filter: EventFilter,
    now: datetime,
) -> SelectT:
    if event_filter.league is not None:
        query = query.where(events_table.c.league == event_filter.league)
    if event_filter.sport is not None:
        query = query.where(events_table.c.sport == event_filter.sport)
    if not event_filter.include_started:
        # An event with no known start time has not started, matching the rule the
        # watch paths already apply.
        query = query.where(
            (events_table.c.starts_at.is_(None)) | (events_table.c.starts_at > now)
        )
    return query


def _row_to_freshness(row: RowMapping) -> EventQuoteFreshness:
    return EventQuoteFreshness(
        quote_count=int(row["quote_count"]),
        book_count=int(row["book_count"] or 0),
        last_ingested_at=_as_utc(row["last_ingested_at"]),
        oldest_line_quoted_at=_as_utc(row["oldest_line_quoted_at"]),
        books_with_unknown_line_age=int(row["books_with_unknown_line_age"] or 0),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; every time this system stores is UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
