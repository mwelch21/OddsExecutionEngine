from backend.app.domain.models import ExecutionRecommendation, OrderIntent, Quote
from backend.app.engines.price_comparison_engine import is_price_fillable


def rank_quotes(quotes: list[Quote]) -> list[Quote]:
    return sorted(quotes, key=lambda quote: (-quote.price, quote.sportsbook))


def generate_recommendation(
    intent: OrderIntent,
    matched_quotes: list[Quote],
) -> ExecutionRecommendation:
    ranked_quotes = rank_quotes(matched_quotes)
    best_quote = ranked_quotes[0] if ranked_quotes else None
    fillable_quotes = [
        quote for quote in ranked_quotes if is_price_fillable(quote.price, intent.target_price)
    ]
    nearest_miss = next(
        (
            quote
            for quote in ranked_quotes
            if not is_price_fillable(quote.price, intent.target_price)
        ),
        None,
    )

    return ExecutionRecommendation(
        intent=intent,
        fillable=bool(fillable_quotes),
        best_quote=fillable_quotes[0] if fillable_quotes else best_quote,
        ranked_quotes=ranked_quotes,
        nearest_miss=None if fillable_quotes else nearest_miss,
        matched_quote_count=len(ranked_quotes),
    )
