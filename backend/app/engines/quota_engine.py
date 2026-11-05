from backend.app.domain.quota import QuotaObservation, QuotaReading, QuotaSource

# The derived floor: this share of the plan (used + remaining), per ADR-016.
DEFAULT_FLOOR_PERCENT = 10


class QuotaEngine:
    """Credit bookkeeping and the quota warning rule of ADR-016.

    The warning fires on a crossing (previous >= floor > now), so staying below
    is silent and rising back above re-arms it. With no previous observation the
    warning is armed: the operator should hear about low credits on day one.
    """

    def observe(
        self, reading: QuotaReading, previous: QuotaObservation | None
    ) -> QuotaObservation:
        if reading.credits_remaining is not None:
            return QuotaObservation(
                remaining=0 if reading.out_of_credits else reading.credits_remaining,
                used=reading.credits_used,
                source=QuotaSource.HEADERS,
                out_of_credits=reading.out_of_credits,
                observed_at=reading.observed_at,
            )

        # A refused call costs nothing; a served one costs markets x regions.
        cost = 0 if reading.out_of_credits else reading.estimated_cost
        remaining = None if previous is None else previous.remaining
        used = None if previous is None else previous.used
        return QuotaObservation(
            remaining=0
            if reading.out_of_credits
            else (None if remaining is None else max(remaining - cost, 0)),
            used=None if used is None else used + cost,
            source=QuotaSource.LOCAL,
            out_of_credits=reading.out_of_credits,
            observed_at=reading.observed_at,
        )

    def floor(self, configured: int | None, latest: QuotaObservation | None) -> int | None:
        if configured is not None:
            return configured
        if latest is None or latest.remaining is None or latest.used is None:
            return None
        return (latest.remaining + latest.used) * DEFAULT_FLOOR_PERCENT // 100

    def should_warn(
        self,
        previous: QuotaObservation | None,
        current: QuotaObservation,
        floor: int | None,
    ) -> bool:
        if floor is None or current.remaining is None or current.remaining >= floor:
            return False
        if previous is None or previous.remaining is None:
            return True
        return previous.remaining >= floor

    def is_paused(self, latest: QuotaObservation | None) -> bool:
        return latest is not None and (latest.out_of_credits or latest.remaining == 0)
