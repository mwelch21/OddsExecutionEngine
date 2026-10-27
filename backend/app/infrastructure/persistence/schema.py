from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

metadata = MetaData()

events_table = Table(
    "events",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("external_id", String(length=255), nullable=False, unique=True),
    Column("starts_at", DateTime(timezone=True), nullable=True),
    Column("sport", String(length=64), nullable=True),
    Column("league", String(length=64), nullable=True),
    Column("status", String(length=16), nullable=False, server_default="upcoming"),
    Column("provider", String(length=32), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

event_participants_table = Table(
    "event_participants",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("event_id", String(length=36), ForeignKey("events.id"), nullable=False),
    Column("participant_name", String(length=128), nullable=False),
    Column("role", String(length=32), nullable=False),
    Column("side", String(length=16), nullable=True),
    Column("sort_order", Integer, nullable=False, server_default="0"),
)

markets_table = Table(
    "markets",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("event_id", String(length=36), ForeignKey("events.id"), nullable=False),
    Column("market_type", String(length=32), nullable=False),
    Column("selection", String(length=64), nullable=False),
    Column("line", Float, nullable=True),
    Column("line_key", String(length=64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "event_id",
        "market_type",
        "selection",
        "line_key",
        name="uq_markets_identity",
    ),
)

market_quotes_latest_table = Table(
    "market_quotes_latest",
    metadata,
    Column("market_id", String(length=36), ForeignKey("markets.id"), primary_key=True),
    Column("sportsbook", String(length=64), primary_key=True),
    Column("price", Integer, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # The book's own line-movement time. NULL means the provider does not expose one,
    # which reads as unknown age — never as freshly moved.
    Column("quoted_at", DateTime(timezone=True), nullable=True),
)

market_quotes_history_table = Table(
    "market_quotes_history",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("market_id", String(length=36), ForeignKey("markets.id"), nullable=False),
    Column("sportsbook", String(length=64), nullable=False),
    Column("price", Integer, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("quoted_at", DateTime(timezone=True), nullable=True),
)

order_intents_table = Table(
    "order_intents",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("event_external_id", String(length=255), nullable=False),
    Column("market_type", String(length=32), nullable=False),
    Column("selection", String(length=64), nullable=False),
    Column("line", Float, nullable=True),
    Column("target_price", Integer, nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

execution_recommendations_table = Table(
    "execution_recommendations",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("order_intent_id", String(length=36), ForeignKey("order_intents.id"), nullable=False),
    Column("fillable", Boolean, nullable=False),
    Column("matched_quote_count", Integer, nullable=False),
    Column("best_quote", JSON, nullable=True),
    Column("nearest_miss", JSON, nullable=True),
    Column("ranked_quotes", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

watch_intents_table = Table(
    "watch_intents",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("event_external_id", String(length=255), nullable=False),
    Column("market_type", String(length=32), nullable=False),
    Column("selection", String(length=64), nullable=False),
    Column("line", Float, nullable=True),
    Column("target_price", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("status", String(length=16), nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

opportunities_table = Table(
    "opportunities",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column(
        "watch_intent_id",
        String(length=36),
        ForeignKey("watch_intents.id"),
        nullable=False,
    ),
    Column("event_external_id", String(length=255), nullable=False),
    Column("market_id", String(length=36), ForeignKey("markets.id"), nullable=False),
    Column("best_sportsbook", String(length=64), nullable=False),
    Column("best_price", Integer, nullable=False),
    Column("matching_quotes", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # A watch names exactly one market and is terminal once it fires, so it can
    # produce at most one opportunity, ever.
    UniqueConstraint("watch_intent_id", name="uq_opportunities_watch_intent"),
)

workflow_events_table = Table(
    "workflow_events",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("event_type", String(length=128), nullable=False),
    Column("aggregate_id", String(length=36), nullable=False),
    Column("workflow_id", String(length=36), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# The public outbox (ADR-014, ADR-015). Each row is one CloudEvents envelope, written
# in the same transaction as the domain change it describes. `dispatched_at` is set by
# the notifier once fan-out into deliveries is complete; Python never sets it.
public_events_table = Table(
    "public_events",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("type", String(length=128), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("dispatched_at", DateTime(timezone=True), nullable=True),
)

# Where public events are delivered (ADR-015). `config` holds channel secrets such as
# the Web Push `auth` key and is never returned by the API. Rows are soft-disabled,
# never deleted.
destinations_table = Table(
    "destinations",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("channel", String(length=32), nullable=False),
    Column("label", String(length=128), nullable=False),
    Column("address", Text, nullable=False),
    Column("config", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_delivered_at", DateTime(timezone=True), nullable=True),
    Column("disabled_at", DateTime(timezone=True), nullable=True),
    Column("disabled_reason", String(length=32), nullable=True),
    UniqueConstraint("channel", "address", name="uq_destinations_channel_address"),
)

# One public event going to one destination (ADR-015). Only the Go notifier writes
# here; the API reads it for status. Alembic still owns the schema (ADR-013).
deliveries_table = Table(
    "deliveries",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("event_id", String(length=36), ForeignKey("public_events.id"), nullable=False),
    Column(
        "destination_id", String(length=36), ForeignKey("destinations.id"), nullable=False
    ),
    Column("status", String(length=16), nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("claim_token", String(length=36), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("event_id", "destination_id", name="uq_deliveries_event_destination"),
)

# Auto-Refresh (ADR-016). A single row, pinned by `id = 1`, holding the operator's
# switch exactly as last set, plus the worker's most recent refresh outcome. The row
# may be absent (a fresh or truncated database): readers treat that as the defaults.
auto_refresh_settings_table = Table(
    "auto_refresh_settings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("enabled", Boolean, nullable=False, server_default="false"),
    Column("interval_minutes", Integer, nullable=False, server_default="5"),
    Column("quota_floor", Integer, nullable=True),
    Column("last_outcome_sport", String(length=64), nullable=True),
    Column("last_outcome_status", String(length=16), nullable=True),
    Column("last_outcome_at", DateTime(timezone=True), nullable=True),
    Column("last_outcome_events_refreshed", Integer, nullable=True),
    Column("last_outcome_error", Text, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("id = 1", name="ck_auto_refresh_settings_single_row"),
    CheckConstraint(
        "interval_minutes BETWEEN 1 AND 60", name="ck_auto_refresh_settings_interval"
    ),
)

# When each provider sport key was last pulled sport-wide, manual or automatic. The
# Auto-Refresh cooldown is derived from it; a per-event refresh does not touch it.
sport_refreshes_table = Table(
    "sport_refreshes",
    metadata,
    Column("sport_key", String(length=64), primary_key=True),
    Column("last_refreshed_at", DateTime(timezone=True), nullable=False),
)
