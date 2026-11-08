import re
from http import HTTPStatus

WITHHELD = "error details withheld"

_GAVE_UP = "gave up: "
_PUSH_ANSWER = re.compile(r"push service answered (\d{3})\b.*", re.DOTALL)
_NETWORK = re.compile(r"network error(: timed out|: [a-z]+ failed)?")
_UNSENDABLE = re.compile(
    r"unsendable push: (notification is \d+ bytes, over the \d+-byte Web Push limit"
    r"|subscription p256dh is not a P-256 public key"
    r"|subscription auth is not a 16-byte secret)"
)
_FIXED = {"past its expiry before send", "destination is gone", "event could not be rendered"}


class DeliveryErrorEngine:
    """A delivery's `last_error` as the operator may see it (#105).

    Allowlist, not a filter: only shapes the notifier is known to write come
    through, rebuilt from the parts that are safe (a status code, a fixed
    reason). Rows written before the notifier summarised its errors can carry
    the push address or the push service's answer body, so they are reduced to
    their kind; anything else is withheld.
    """

    def summary(self, stored: str | None) -> str | None:
        if stored is None:
            return None
        if stored.startswith(_GAVE_UP):
            return _GAVE_UP + _reason(stored.removeprefix(_GAVE_UP))
        return _reason(stored)


def _reason(text: str) -> str:
    if text in _FIXED or _NETWORK.fullmatch(text) or _UNSENDABLE.fullmatch(text):
        return text
    if answer := _PUSH_ANSWER.fullmatch(text):
        code = int(answer.group(1))
        try:
            return f"push service answered {code} {HTTPStatus(code).phrase}"
        except ValueError:
            return f"push service answered {code}"
    # Legacy shapes, reduced to their kind.
    if text.startswith("sending push: "):
        return "network error"
    if text.startswith(("decoding ", "no renderer for ")):
        return "event could not be rendered"
    if text.startswith("unsendable push: encoding notification: "):
        return "unsendable push: notification could not be encoded"
    return WITHHELD
