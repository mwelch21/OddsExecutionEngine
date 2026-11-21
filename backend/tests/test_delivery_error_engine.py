import pytest

from backend.app.engines.delivery_error_engine import WITHHELD, DeliveryErrorEngine

PUSH_ADDRESS = "https://web.push.apple.com/QSecretSubscriptionToken"
TOKEN = "tok_SECRET_9f8e7d6c5b4a"


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        # What the notifier writes today passes through.
        ("push service answered 400 Bad Request", "push service answered 400 Bad Request"),
        ("gave up: push service answered 503 Service Unavailable",
         "gave up: push service answered 503 Service Unavailable"),
        ("network error: timed out", "network error: timed out"),
        ("gave up: network error: dial failed", "gave up: network error: dial failed"),
        ("network error", "network error"),
        ("past its expiry before send", "past its expiry before send"),
        ("destination is gone", "destination is gone"),
        ("event could not be rendered", "event could not be rendered"),
        ("unsendable push: subscription auth is not a 16-byte secret",
         "unsendable push: subscription auth is not a 16-byte secret"),
        ("unsendable push: notification is 5000 bytes, over the 3993-byte Web Push limit",
         "unsendable push: notification is 5000 bytes, over the 3993-byte Web Push limit"),
        # Rows written before the notifier summarised its errors.
        (f"push service answered 410: {PUSH_ADDRESS} expired {TOKEN}",
         "push service answered 410 Gone"),
        (f"gave up: push service answered 429: {TOKEN}",
         "gave up: push service answered 429 Too Many Requests"),
        (f'sending push: Post "{PUSH_ADDRESS}": dial tcp: lookup failed',
         "network error"),
        (f'gave up: sending push: Post "{PUSH_ADDRESS}": EOF', "gave up: network error"),
        ("decoding oddsengine.opportunity.identified.v1 data: json: cannot unmarshal",
         "event could not be rendered"),
        ("no renderer for oddsengine.something.v1", "event could not be rendered"),
        ("unsendable push: encoding notification: json: unsupported value",
         "unsendable push: notification could not be encoded"),
    ],
)
def test_known_errors_show_as_a_safe_summary(stored: str, shown: str) -> None:
    assert DeliveryErrorEngine().summary(stored) == shown


@pytest.mark.parametrize(
    "stored",
    [
        f"something new happened at {PUSH_ADDRESS}",
        TOKEN,
        f"unsendable push: subscription auth {TOKEN} is wrong",
        f"network error: {PUSH_ADDRESS}",
        "push service answered",
    ],
)
def test_anything_unrecognised_is_withheld(stored: str) -> None:
    assert DeliveryErrorEngine().summary(stored) == WITHHELD


def test_no_error_stays_none() -> None:
    assert DeliveryErrorEngine().summary(None) is None
