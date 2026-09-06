from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.sql import func

metadata = MetaData()

events_table = Table(
    "events",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("external_id", String(length=255), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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
    Column("quoted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

market_quotes_history_table = Table(
    "market_quotes_history",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column("market_id", String(length=36), ForeignKey("markets.id"), nullable=False),
    Column("sportsbook", String(length=64), nullable=False),
    Column("price", Integer, nullable=False),
    Column("quoted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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
    Column("status", String(length=16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

opportunity_signals_table = Table(
    "opportunity_signals",
    metadata,
    Column("id", String(length=36), primary_key=True),
    Column(
        "watch_intent_id",
        String(length=36),
        ForeignKey("watch_intents.id"),
        nullable=False,
    ),
    Column("event_external_id", String(length=255), nullable=False),
    Column("market_type", String(length=32), nullable=False),
    Column("selection", String(length=64), nullable=False),
    Column("line", Float, nullable=True),
    Column("matched_price", Integer, nullable=False),
    Column("target_price", Integer, nullable=False),
    Column("sportsbook", String(length=64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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
