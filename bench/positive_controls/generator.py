"""
Synthetic positive control generator for Autonoma SEC002 recall validation.

Generates structurally valid, cryptographically inert credentials using
format-inspired synthetic controls with safe alias prefixes. Output is
deterministic given a seed, so the same controls can be regenerated for
verification without committing values to public git.

Usage:
    python generator.py --seed 42 --per-family 10 --out controls_manifest.json

Critical properties:
  - Safe alias prefixes (stk_live_, ght_, AXIA, GIZA, xotb-, ...) preserve
    structural and entropy realism without using any real provider-valid prefix.
  - Random payloads from a seeded RNG. Payloads are NOT issued by any provider
    and will fail provider validation.
  - Output manifest is intended to stay PRIVATE. Only the seed is published.
  - Two control categories: vendor-shaped and generic opaque credential-shaped.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import string
import sys
import zlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Character sets
# ---------------------------------------------------------------------------

BASE62 = string.ascii_letters + string.digits
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
HEX_UPPER = string.digits + "ABCDEF"
B64URL = string.ascii_letters + string.digits + "-_"


def _rand_str(rng: random.Random, alphabet: str, length: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Vendor-shaped controls (format-inspired, safe alias prefixes)
# Each returns (value, expected_format_description)
# ---------------------------------------------------------------------------

def gen_stripe(rng: random.Random) -> tuple[str, str]:
    # stk_live_ + 24 base62 chars (alias for real sk_live_ prefix)
    payload = _rand_str(rng, BASE62, 24)
    return f"stk_live_{payload}", "stripe_secret_live"


def gen_github_pat(rng: random.Random) -> tuple[str, str]:
    # ght_ + 36 base62 chars (alias for real ghp_ prefix).
    # Body + CRC32 checksum tail to preserve structural realism.
    body = _rand_str(rng, BASE62, 30)
    crc = zlib.crc32(body.encode()) & 0xFFFFFFFF
    checksum_chars = []
    n = crc
    for _ in range(6):
        checksum_chars.append(BASE62[n % 62])
        n //= 62
    checksum = "".join(reversed(checksum_chars))
    return f"ght_{body}{checksum}", "github_pat_v2"


def gen_aws_pair(rng: random.Random) -> tuple[str, str]:
    # Access key: AXIA + 16 uppercase alphanumeric (alias for real AKIA prefix).
    # Secret key: 40 chars base64-ish (alphanumeric + / +).
    access_alphabet = string.ascii_uppercase + string.digits
    access = "AXIA" + _rand_str(rng, access_alphabet, 16)
    secret_alphabet = string.ascii_letters + string.digits + "/+"
    secret = _rand_str(rng, secret_alphabet, 40)
    return f"{access}|{secret}", "aws_access_key_pair"


def gen_google_api_key(rng: random.Random) -> tuple[str, str]:
    # GIZA + 35 chars base62-ish (alias for real AIza prefix).
    payload_alphabet = BASE62 + "-_"
    payload = _rand_str(rng, payload_alphabet, 35)
    return f"GIZA{payload}", "google_api_key"


def gen_slack_bot_token(rng: random.Random) -> tuple[str, str]:
    # xotb-<workspace_id>-<bot_id>-<token_secret> (alias for real xoxb- prefix)
    ws = _rand_str(rng, string.digits, 12)
    bot = _rand_str(rng, string.digits, 12)
    secret = _rand_str(rng, BASE62, 24)
    return f"xotb-{ws}-{bot}-{secret}", "slack_bot_token"


def gen_jwt(rng: random.Random) -> tuple[str, str]:
    # Real three-segment JWT. Header decodes to valid JSON.
    header = json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":"))
    payload = json.dumps(
        {
            "sub": _rand_str(rng, string.digits, 10),
            "name": _rand_str(rng, string.ascii_lowercase, 8),
            "iat": rng.randint(1_700_000_000, 1_800_000_000),
        },
        separators=(",", ":"),
    )
    h_b64 = base64.urlsafe_b64encode(header.encode()).rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    sig = _rand_str(rng, B64URL, 43)  # HS256 signatures are 43 b64url chars
    return f"{h_b64}.{p_b64}.{sig}", "jwt_hs256"


def gen_pem_private_key(rng: random.Random) -> tuple[str, str]:
    # PEM envelope with realistic multiline structure. Body is ~288 base64 chars
    # (216 raw bytes), well within the 256-384 byte target range.
    body_bytes = bytes(rng.randint(0, 255) for _ in range(216))
    b64 = base64.b64encode(body_bytes).decode()
    wrapped = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        f"{wrapped}\n"
        "-----END RSA PRIVATE KEY-----"
    )
    return pem, "pem_rsa_private_key"


# ---------------------------------------------------------------------------
# Generic opaque credential-shaped controls (no vendor prefix)
# ---------------------------------------------------------------------------

def gen_generic_bearer(rng: random.Random) -> tuple[str, str]:
    # No canonical prefix. 40 chars base64url, high entropy.
    payload = _rand_str(rng, B64URL, 40)
    return payload, "generic_bearer_token"


def gen_opaque_api_secret(rng: random.Random) -> tuple[str, str]:
    # No vendor prefix. 32 mixed-charset chars.
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    payload = _rand_str(rng, alphabet, 32)
    return payload, "opaque_api_secret"


def gen_opaque_session_token(rng: random.Random) -> tuple[str, str]:
    # No vendor prefix. 36 chars base62 + hyphen segments.
    part1 = _rand_str(rng, BASE62, 8)
    part2 = _rand_str(rng, BASE62, 12)
    part3 = _rand_str(rng, BASE62, 12)
    return f"{part1}-{part2}-{part3}", "opaque_session_token"


def gen_opaque_random_cred(rng: random.Random) -> tuple[str, str]:
    # High-entropy credential, mixed char classes, variable length, no prefix.
    length = rng.randint(24, 40)
    alphabet = string.ascii_letters + string.digits + "_-"
    payload = _rand_str(rng, alphabet, length)
    return payload, "opaque_random_credential"


FAMILIES = {
    # Vendor-shaped: format-inspired, safe alias prefixes (no real provider prefix)
    "stripe": gen_stripe,
    "github_pat": gen_github_pat,
    "aws_pair": gen_aws_pair,
    "google_api": gen_google_api_key,
    "slack_bot": gen_slack_bot_token,
    "jwt": gen_jwt,
    "pem_private": gen_pem_private_key,
    # Generic opaque: no vendor prefix, tests prefix-independent detection
    "generic_bearer": gen_generic_bearer,
    "opaque_api_secret": gen_opaque_api_secret,
    "opaque_session_token": gen_opaque_session_token,
    "opaque_random_cred": gen_opaque_random_cred,
}


# ---------------------------------------------------------------------------
# Manifest types
# ---------------------------------------------------------------------------

@dataclass
class Control:
    id: str
    family: string
    expected_format: str
    value: str

    def redacted(self, seed: int) -> dict:
        d = asdict(self)
        d["value"] = f"<REDACTED — regenerate via generator.py --seed {seed}>"
        return d


@dataclass
class Manifest:
    schema_version: str
    seed: int
    per_family: int
    generated_at: str
    generator_commit: str | None
    controls: list[Control]

    def to_dict(self, *, redact: bool) -> dict:
        return {
            "schema_version": self.schema_version,
            "seed": self.seed,
            "per_family": self.per_family,
            "generated_at": self.generated_at,
            "generator_commit": self.generator_commit,
            "controls": [
                c.redacted(self.seed) if redact else asdict(c)
                for c in self.controls
            ],
        }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def generate(seed: int, per_family: int, generator_commit: str | None = None) -> Manifest:
    rng = random.Random(seed)
    controls: list[Control] = []
    for family_name, fn in FAMILIES.items():
        for i in range(per_family):
            value, expected_format = fn(rng)
            controls.append(
                Control(
                    id=f"{family_name}_{i:03d}",
                    family=family_name,
                    expected_format=expected_format,
                    value=value,
                )
            )
    return Manifest(
        schema_version="1.0",
        seed=seed,
        per_family=per_family,
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator_commit=generator_commit,
        controls=controls,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Generate Autonoma synthetic positive controls.")
    p.add_argument("--seed", type=int, required=True, help="RNG seed (publish this; keep values private)")
    p.add_argument("--per-family", type=int, required=True, help="Controls per credential family")
    p.add_argument("--out", type=Path, required=True, help="Output manifest path (PRIVATE)")
    p.add_argument("--out-redacted", type=Path, default=None, help="Optional redacted manifest path (publishable)")
    p.add_argument("--generator-commit", type=str, default=None, help="Git SHA of this generator script")
    args = p.parse_args()

    if args.per_family < 1:
        print("--per-family must be >= 1", file=sys.stderr)
        return 2

    manifest = generate(args.seed, args.per_family, args.generator_commit)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest.to_dict(redact=False), indent=2))
    print(f"Wrote private manifest with {len(manifest.controls)} controls to {args.out}")

    if args.out_redacted:
        args.out_redacted.parent.mkdir(parents=True, exist_ok=True)
        args.out_redacted.write_text(json.dumps(manifest.to_dict(redact=True), indent=2))
        print(f"Wrote redacted manifest to {args.out_redacted}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
