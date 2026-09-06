from backend.app.domain.models import MarketType


def validate_market_fields(
    market_type: MarketType,
    selection: str,
    line: float | None,
) -> None:
    if market_type is MarketType.MONEYLINE and line is not None:
        raise ValueError("line must be omitted for moneyline requests")

    if market_type in {MarketType.SPREAD, MarketType.TOTAL} and line is None:
        raise ValueError("line is required for spread and total requests")

    if market_type is MarketType.TOTAL and selection not in {"over", "under"}:
        raise ValueError("selection must be 'over' or 'under' for total requests")
