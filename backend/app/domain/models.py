from datetime import UTC, datetime
from enum import StrEnum

from backend.app.domain.base import DomainModel


class MarketType(StrEnum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"


class EventStatus(StrEnum):
    """Where an event is in its life, as last observed from the provider (#38).

    Written at ingest, never inferred from `starts_at` alone: an event past its
    start time is `live` only while the provider still offers it, and `ended`
    once a pull no longer does.
    """

    UPCOMING = "upcoming"
    LIVE = "live"
    ENDED = "ended"


class LinePhase(StrEnum):
    """Whether a stored line was pulled before kickoff or while the event was live.

    Stamped on each quote at ingest from the event's observed status, so a reader
    never has to guess which kind of line it is looking at.
    """

    PRE_GAME = "pre_game"
    LIVE = "live"


class EventListStatus(StrEnum):
    """Which events a browse request lists. `all` is upcoming plus live.

    Ended events are never listed: nothing on them can fill.
    """

    UPCOMING = "upcoming"
    LIVE = "live"
    ALL = "all"

    @classmethod
    def resolve(
        cls, status: "EventListStatus | None", include_started: bool | None
    ) -> "EventListStatus":
        """The filter a request asks for (ADR-019).

        An explicit `status` wins. The deprecated `include_started` alias applies
        only when it is absent: true reads as all, false as upcoming.
        """
        if status is not None:
            return status
        if include_started is not None:
            return cls.ALL if include_started else cls.UPCOMING
        return cls.ALL


class FillableSkipReason(StrEnum):
    """Why an event rules out every quote a watch could fill on."""

    EVENT_ENDED = "event_ended"
    # Stored upcoming but past its start: not observed since kickoff, so its
    # pre-game lines may be gone and its live lines are unknown.
    EVENT_STATUS_UNOBSERVED = "event_status_unobserved"


class EventObservation(DomainModel):
    """What one provider answer said about an event's life, and when (#38).

    `observed_at` is when the answer's data was current. A write carrying an
    observation older than the one stored is skipped, so an older pull landing
    late can never overwrite a newer one. `starts_at` is None when the answer
    did not carry a start time; the stored one is then kept.
    """

    status: EventStatus
    observed_at: datetime
    starts_at: datetime | None = None


class EventLifecycle(DomainModel):
    """What a stored event records about where it is in its life."""

    status: EventStatus
    starts_at: datetime | None = None


class OrderIntent(DomainModel):
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    line: float | None = None


class Quote(DomainModel):
    """One book's price, carrying when the book moved it and when we pulled it.

    `quoted_at` is the sportsbook's own line-movement time as reported by the
    provider. `ingested_at` is when we read it. They are never the same fact: a
    line untouched for three days and pulled ten seconds ago is three days old,
    not ten seconds old. Providers that expose no line-movement time leave
    `quoted_at` as None, which reads as unknown age rather than freshly moved.
    """

    event_id: str
    sportsbook: str
    market_type: MarketType
    selection: str
    price: int
    line: float | None = None
    quoted_at: datetime | None = None
    ingested_at: datetime | None = None
    # Stamped at ingest from the event's observed status; None on a quote fresh
    # from a provider. Storage treats None as pre_game.
    phase: LinePhase | None = None

    @property
    def line_age_known(self) -> bool:
        """True only when the book's own line-movement time is available."""
        return self.quoted_at is not None

    @property
    def effective_quoted_at(self) -> datetime | None:
        """Best available age reference: the book's time, else the ingest time."""
        return self.quoted_at if self.quoted_at is not None else self.ingested_at


class FillableQuotes(DomainModel):
    """The stored quotes a watch may fill on, and why there are none if so."""

    quotes: list[Quote]
    # Set only when the event itself rules every quote out.
    skipped_reason: FillableSkipReason | None = None


class PersistedQuote(DomainModel):
    quote: Quote
    market_id: str
    market_created: bool


class QuoteRefreshPersistenceResult(DomainModel):
    event_id: str
    persisted_quotes: list[PersistedQuote]
    created_market_count: int
    updated_latest_count: int
    appended_history_count: int
    # True only when this refresh's observation was written: a stale one is
    # skipped, and must then close no watch window (ADR-017).
    status_written: bool = False


class QuoteRefreshSummary(DomainModel):
    event_id: str
    ingested_quote_count: int
    created_market_count: int
    updated_latest_count: int
    appended_history_count: int
    emitted_event_types: list[str]


class ExecutionRecommendation(DomainModel):
    intent: OrderIntent
    fillable: bool
    best_quote: Quote | None
    ranked_quotes: list[Quote]
    nearest_miss: Quote | None
    matched_quote_count: int


class WatchStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    TRIGGERED = "triggered"


class WatchWindow(StrEnum):
    """Which part of an event's life a watch covers (ADR-017). Always stored.

    The same target price means a different bet before the game and during it,
    so a watch says which lines it may fill on:

    - `pre_game`: pre-game lines only; expires when the event starts.
    - `live`: live lines only; expires when the event ends.
    - `full_game`: either; expires when the event ends.
    """

    PRE_GAME = "pre_game"
    LIVE = "live"
    FULL_GAME = "full_game"


class ExpiredReason(StrEnum):
    """Why a watch expired (ADR-017)."""

    TTL = "ttl"
    EVENT_STARTED = "event_started"
    EVENT_ENDED = "event_ended"
    # Defined for the contract; nothing writes it until a cancel signal exists (#127).
    EVENT_CANCELLED = "event_cancelled"


class WatchIntent(DomainModel):
    id: str
    event_id: str
    market_type: MarketType
    selection: str
    target_price: int
    # No default here: `WatchWindowPolicy` is the only place a default lives.
    window: WatchWindow
    line: float | None = None
    expires_at: datetime | None = None
    status: WatchStatus = WatchStatus.ACTIVE
    # Set only on an expired watch.
    expired_reason: ExpiredReason | None = None
    created_at: datetime | None = None

    def is_expired_at(self, now: datetime) -> bool:
        """True once the watch's TTL has passed. Never evaluated again after this."""
        if self.expires_at is None:
            return False

        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        return expires_at <= now

    def effective_status(self, now: datetime) -> WatchStatus:
        """Status a reader should see.

        Expiry is applied when an event is next evaluated, so a watch whose TTL passed
        while no quotes refreshed is still stored as `active`. It can never produce an
        opportunity, so reads must not present it as live.
        """
        if self.status is WatchStatus.ACTIVE and self.is_expired_at(now):
            return WatchStatus.EXPIRED

        return self.status

    def with_effective_status(self, now: datetime) -> "WatchIntent":
        status = self.effective_status(now)
        if status is self.status:
            return self

        # Only a passed TTL changes status on read; lifecycle expiry is stored.
        return self.model_copy(update={"status": status, "expired_reason": ExpiredReason.TTL})


class MatchingQuote(DomainModel):
    """One book that was fillable when the opportunity was identified."""

    sportsbook: str
    price: int


class Opportunity(DomainModel):
    """A watch's single terminal hit, carrying every book that was fillable.

    `matching_quotes` is the snapshot taken at detection time, ranked best-first.
    `best_sportsbook` / `best_price` mirror its head so the common query stays
    SQL-native, and staleness is judged against the best book alone.
    """

    id: str
    watch_intent_id: str
    event_id: str
    market_id: str
    market_type: MarketType
    selection: str
    target_price: int
    best_sportsbook: str
    best_price: int
    matching_quotes: list[MatchingQuote]
    line: float | None = None
    # The phase of the best book's line: a live opportunity is a different bet.
    phase: LinePhase = LinePhase.PRE_GAME
    created_at: datetime | None = None


class OpportunityWithValidity(DomainModel):
    opportunity: Opportunity
    is_valid: bool
    reason: str | None = None


class WatchIntentCreationResult(DomainModel):
    """What creating a watch produced, including an opportunity it filled at once.

    Creation still evaluates immediately, so a watch can come back already
    `triggered`. Returning the opportunity with it saves the caller a second
    request to learn an answer the same transaction already computed.
    """

    watch_intent: WatchIntent
    opportunity: Opportunity | None = None


class EventParticipant(DomainModel):
    name: str
    role: str = "team"
    side: str | None = None
    sort_order: int = 0


class EventInfo(DomainModel):
    id: str
    sport: str
    league: str | None = None
    participants: list[EventParticipant] = []
    commence_time: datetime | None = None


class UpstreamQuota(DomainModel):
    """What one upstream call cost, and what is left.

    The Odds API bills credits, not requests: a call costs
    [markets] x [regions], so a single refresh of three markets in one region
    spends three. `credits_spent` is that call's own cost (`x-requests-last`).

    Every field is nullable because the headers are not guaranteed: a provider
    may omit them, and a failed response may carry none at all. `None` reads as
    "not reported", never as zero — a refresh that appears to have cost nothing
    is a claim this system cannot make.
    """

    credits_spent: int | None = None
    credits_remaining: int | None = None


class ProviderFetchReport(DomainModel):
    """Whether a refresh actually contacted the provider, and what it cost.

    `upstream_contacted` is false when the answer came from a reused response.
    `quota` is populated only when it is true: replaying the credit figures from
    someone else's earlier call would misreport both the cost and the balance.
    """

    upstream_contacted: bool
    data_age_seconds: float
    quota: UpstreamQuota | None = None
    # The quota observation of the call that produced the data. Callers coalesced
    # onto one call get the same id, so their refreshes link to one call (#104).
    observation_id: int | None = None
    # Per-event fetch only: did the provider still offer the event? False on a 404
    # or an empty answer; None when the provider does not say (#38).
    event_offered: bool | None = None
    # When the provider's response arrived. Orders status writes and classifies
    # kickoff; a reused response keeps its original time. None when unknown.
    answered_at: datetime | None = None


class EventSport(DomainModel):
    """What a stored event records about its sport, in our vocabulary.

    Both fields are nullable because the columns are: an event first seen through
    a bare per-event refresh was stored before anything told us its sport.
    """

    sport: str | None = None
    league: str | None = None


class SupportedSport(DomainModel):
    """A sport this system knows how to ingest, named in both vocabularies.

    `key` is the provider's own sport key and the value a refresh request carries.
    `sport` and `league` are what that key splits into once stored, and what a
    client should display — a user picks "NFL", not `americanfootball_nfl`.
    """

    key: str
    sport: str
    league: str | None = None


class SportRefreshResult(DomainModel):
    """One sport-wide refresh: what it persisted, and what it cost to find out.

    The per-event summaries and the fetch report are returned together because
    the router previously assembled this shape itself, and the cost of a refresh
    is not derivable from the summaries.
    """

    sport: str
    summaries: list[QuoteRefreshSummary]
    fetch_report: ProviderFetchReport


class EventQuoteFreshness(DomainModel):
    """How old an event's quotes are, keeping our clock and the books' apart.

    `last_ingested_at` is when we last pulled this event. `oldest_line_quoted_at`
    is the oldest line-movement time among the books that report one — the worst
    case a reader is actually looking at, since "we pulled recently" says nothing
    about whether any line has moved.

    An event nobody has refreshed has `quote_count == 0` and no times at all,
    which is not the same fact as age zero. Books that expose no line-movement
    time are counted in `books_with_unknown_line_age` rather than folded into the
    age, so the reported oldest can never be read as covering every book —
    `book_count` is the denominator that makes that number legible.

    `quote_count` counts stored quotes; `book_count` counts distinct sportsbooks.
    One book quoting both sides of three markets is six quotes and one book.
    """

    quote_count: int = 0
    book_count: int = 0
    last_ingested_at: datetime | None = None
    oldest_line_quoted_at: datetime | None = None
    books_with_unknown_line_age: int = 0


class EventSummary(DomainModel):
    """One event as the browse list shows it: matchup, start time, quote age."""

    id: str
    sport: str | None = None
    league: str | None = None
    status: EventStatus = EventStatus.UPCOMING
    starts_at: datetime | None = None
    participants: list[EventParticipant] = []
    quotes: EventQuoteFreshness = EventQuoteFreshness()


class MarketQuotes(DomainModel):
    """One market and the books quoting it, in whatever order storage returned.

    Ranking is not storage's job: the board's order has to come from the same
    engine rule the recommendation and watch paths apply, so this carries the
    quotes unranked and the application layer ranks them.
    """

    market_type: MarketType
    selection: str
    line: float | None = None
    quotes: list[Quote] = []


class LineBoardMarket(DomainModel):
    """One market's books, ranked best-first, with the best one named.

    `best_sportsbook` / `best_price` mirror the head of `quotes`, the same way
    `Opportunity` mirrors the head of its matching quotes. They exist so a client
    never re-sorts to find the best book: two books at an identical price are
    separated only by the engine's tie-break, and a client sorting for itself can
    show a different winner than the one a watch on this market would fire on.

    A market nobody is quoting has no best book — never a best book at price
    zero — so both fields are None when `quotes` is empty.
    """

    market_type: MarketType
    selection: str
    line: float | None = None
    quotes: list[Quote] = []
    best_sportsbook: str | None = None
    best_price: int | None = None

    @classmethod
    def from_ranked(
        cls, market: MarketQuotes, ranked_quotes: list[Quote]
    ) -> "LineBoardMarket":
        """Pair a market with its books once someone else has ranked them.

        Ranking is the engine's call, so it happens outside; naming the winner is
        just reading the head of what the engine returned.
        """
        best = ranked_quotes[0] if ranked_quotes else None
        return cls(
            market_type=market.market_type,
            selection=market.selection,
            line=market.line,
            quotes=ranked_quotes,
            best_sportsbook=best.sportsbook if best is not None else None,
            best_price=best.price if best is not None else None,
        )


class LineBoard(DomainModel):
    """Everything needed to render one event's line board in a single answer.

    Deliberately unpaged: one event's markets are bounded and render as one
    screen, and paging them would mean a client reassembling pages before it
    could display anything.
    """

    event: EventSummary
    markets: list[LineBoardMarket] = []


class EventFilter(DomainModel):
    """What a browse request is asking for.

    League and sport narrow independently and combine. `status` picks upcoming,
    live, or both (the default); ended events are never listed (#38).

    `sport_leagues` is a set of stored (sport, league) pairs an event must be in,
    resolved from catalog sport keys (#132). None means no such filter; empty
    matches nothing, as a key outside the catalog does. It combines with the rest.
    """

    league: str | None = None
    sport: str | None = None
    status: EventListStatus = EventListStatus.ALL
    sport_leagues: tuple[tuple[str, str | None], ...] | None = None


class EventPage(DomainModel):
    """A page of events plus everything needed to render "page 2 of 7"."""

    events: list[EventSummary]
    page: int
    page_size: int
    total_events: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return -(-self.total_events // self.page_size)
