from typing import Any

from backend.app.domain.public_events import (
    DESTINATION_TEST_V1,
    OPPORTUNITY_IDENTIFIED_V1,
    QUOTA_WARNING_V1,
)


class DeliverySubjectEngine:
    """The delivery log's one-line subject for a public event (#105).

    Mirrors what the notifier shows on the device, from the few fields it needs,
    so the log never has to carry the raw payload. An event type it does not
    know, or data it cannot read, falls back to the event type.
    """

    def subject_for(self, event_type: str, data: dict[str, Any]) -> str:
        try:
            if event_type == DESTINATION_TEST_V1:
                return "Test notification"
            if event_type == OPPORTUNITY_IDENTIFIED_V1:
                return _opportunity_subject(data)
            if event_type == QUOTA_WARNING_V1:
                return f"Credits running low · {int(data['remaining'])} left"
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
        return event_type


def _opportunity_subject(data: dict[str, Any]) -> str:
    selection = _display_name(data["selection"])
    line = data.get("line")
    if line is not None:
        text = f"{float(line):g}"
        if data.get("market_type") == "spread" and float(line) > 0:
            text = f"+{text}"
        selection = f"{selection} {text}"
    best = data["best"]
    subject = f"{selection} {_american(int(best['price']))} @ {best['sportsbook']}"
    event = data.get("event") or {}
    if event.get("away") and event.get("home"):
        return f"{event['away']} @ {event['home']} · {subject}"
    return subject


def _display_name(key: str) -> str:
    return " ".join(word[:1].upper() + word[1:] for word in key.replace("_", " ").split())


def _american(price: int) -> str:
    return f"+{price}" if price > 0 else str(price)
