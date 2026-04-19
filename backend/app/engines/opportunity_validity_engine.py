from datetime import UTC, datetime, timedelta, timezone

from backend.app.domain.models import Opportunity, OpportunityWithValidity


def _ensure_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (default to UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class OpportunityValidityEngine:
    def check_validity(
        self,
        opportunity: Opportunity,
        latest_quote_time: datetime | None,
        ttl_minutes: int,
        now: datetime,
    ) -> OpportunityWithValidity:
        if opportunity.created_at is None:
            return OpportunityWithValidity(
                opportunity=opportunity, is_valid=False, reason="missing_timestamp"
            )

        created = _ensure_aware(opportunity.created_at)
        now_aware = _ensure_aware(now)

        if now_aware - created > timedelta(minutes=ttl_minutes):
            return OpportunityWithValidity(
                opportunity=opportunity, is_valid=False, reason="expired"
            )

        if latest_quote_time is None:
            return OpportunityWithValidity(
                opportunity=opportunity, is_valid=False, reason="quote_removed"
            )

        quote_time = _ensure_aware(latest_quote_time)
        if quote_time > created:
            return OpportunityWithValidity(
                opportunity=opportunity, is_valid=False, reason="quote_superseded"
            )

        return OpportunityWithValidity(opportunity=opportunity, is_valid=True)

    def check_validity_batch(
        self,
        items: list[tuple[Opportunity, datetime | None]],
        ttl_minutes: int,
        now: datetime,
    ) -> list[OpportunityWithValidity]:
        return [
            self.check_validity(opportunity, latest_quote_time, ttl_minutes, now)
            for opportunity, latest_quote_time in items
        ]
