"""Generate the VAPID key pair for Web Push and write it into .env.

    uv run python scripts/generate_vapid_keys.py --subject mailto:you@example.com

Writes three variables:

- VAPID_PUBLIC_KEY   handed to browsers by the API so they can subscribe
- VAPID_PRIVATE_KEY  signs pushes; only the notifier service may receive it
- VAPID_SUBJECT      contact the push services can reach (mailto: or https:)

Both keys are base64url without padding: the public key is the uncompressed P-256
point (65 bytes), the private key the raw 32-byte scalar, which is the form
webpush-go expects.

Existing keys are kept unless --force is given. Rotating the pair breaks every
current subscription: each device must subscribe again before it receives anything.
"""

import argparse
import base64
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
KEYS = ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_key_pair() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    private_raw = private_key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public_raw), _b64url(private_raw)


def _set_vars(text: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        line = f"{name}={value}"
        pattern = re.compile(rf"^{name}=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(line, text)
        else:
            text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--subject",
        required=True,
        help="Contact for push services, e.g. mailto:you@example.com",
    )
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing keys. Every device must re-subscribe afterwards.",
    )
    args = parser.parse_args()

    if not re.match(r"^(mailto:|https://)", args.subject):
        parser.error("--subject must start with mailto: or https://")

    text = args.env_file.read_text() if args.env_file.exists() else ""
    if re.search(r"^VAPID_PRIVATE_KEY=.+$", text, re.MULTILINE) and not args.force:
        print(
            f"{args.env_file} already has VAPID keys. Keeping them.\n"
            "Pass --force to rotate; every device must then subscribe again.",
            file=sys.stderr,
        )
        return 1

    public_key, private_key = generate_key_pair()
    args.env_file.write_text(
        _set_vars(
            text,
            {
                "VAPID_PUBLIC_KEY": public_key,
                "VAPID_PRIVATE_KEY": private_key,
                "VAPID_SUBJECT": args.subject,
            },
        )
    )
    args.env_file.chmod(0o600)
    print(f"Wrote {', '.join(KEYS)} to {args.env_file}")
    print("Restart the API so it serves the new public key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
