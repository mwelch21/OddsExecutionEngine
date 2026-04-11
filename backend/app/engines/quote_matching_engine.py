from backend.app.domain.models import OrderIntent, Quote


def match_quotes(intent: OrderIntent, quotes: list[Quote]) -> list[Quote]:
    return [
        quote
        for quote in quotes
        if quote.event_id == intent.event_id
        and quote.market_type == intent.market_type
        and quote.selection == intent.selection
        and quote.line == intent.line
    ]
