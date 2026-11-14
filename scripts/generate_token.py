"""
LiveKit Token Generator for WebRTC Playground, Console & Verified Caller Testing.

Supports embedding cryptographically signed participant attributes (`caller_phone`,
`lang`, `tenant_id`, `branch_id`) inside the LiveKit JWT so the clinic voice worker
can enforce verified caller identity without trusting spoken phone numbers.

Usage:
    uv run python scripts/generate_token.py
    uv run python scripts/generate_token.py --room clinic-room --identity patient_01 --phone 01012345678 --lang ar
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from livekit import api

from src.config import Settings, get_settings, settings
from src.db.schemas import clean_egyptian_phone

_DEV_ENVIRONMENTS: frozenset[str] = frozenset(
    {"dev", "development", "test", "testing", "local"}
)


def _normalize_token_phone(raw_phone: str | None) -> str | None:
    """Normalize and strictly validate Egyptian mobile numbers for JWT signing."""
    if raw_phone is None:
        return None
    stripped = str(raw_phone).strip()
    if not stripped:
        return None
    return clean_egyptian_phone(stripped)


def generate_livekit_token(
    room_name: str = "test-voice-room",
    identity: str = "caller_web",
    name: str = "Voice Tester",
    valid_hours: int = 24,
    *,
    caller_phone: str | None = None,
    phone: str | None = None,
    lang: str | None = None,
    tenant_id: str | None = None,
    branch_id: str | None = None,
    api_key: str | None = None,
    api_secret: str | None = None,
    settings_obj: Settings | None = None,
) -> str:
    """
    Generate a signed LiveKit JWT token for room join with audio publish/subscribe grants
    and verified caller participant attributes (`caller_phone`, `lang`, `tenant_id`, `branch_id`).
    """
    cfg = settings_obj or get_settings()
    is_dev_env = (cfg.environment or "").strip().lower() in _DEV_ENVIRONMENTS

    raw_key = (api_key if api_key is not None else cfg.livekit_api_key or "").strip()
    raw_secret = (
        api_secret if api_secret is not None else cfg.livekit_api_secret or ""
    ).strip()

    key_missing = not raw_key or raw_key.lower().startswith("your_") or "your_" in raw_key
    secret_missing = (
        not raw_secret or raw_secret.lower().startswith("your_") or "your_" in raw_secret
    )

    if not is_dev_env and (key_missing or secret_missing):
        raise ValueError(
            f"LiveKit API key and secret are required when environment={cfg.environment!r}; "
            "offline devkey fallback is restricted to development/test environments."
        )

    eff_key = "devkey" if key_missing else raw_key
    eff_secret = (
        "secret123456789012345678901234567890" if secret_missing else raw_secret
    )

    eff_phone = _normalize_token_phone(caller_phone if caller_phone is not None else phone)
    eff_lang = (lang or cfg.deepgram_language or "ar").strip()
    eff_tenant = (tenant_id or "default").strip()
    eff_branch = (branch_id or "main").strip()

    attributes: dict[str, str] = {
        "lang": eff_lang,
        "tenant_id": eff_tenant,
        "branch_id": eff_branch,
    }
    if eff_phone:
        attributes["caller_phone"] = eff_phone

    token = (
        api.AccessToken(eff_key, eff_secret)
        .with_identity(identity)
        .with_name(name)
        .with_attributes(attributes)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_ttl(datetime.timedelta(hours=valid_hours))
        .to_jwt()
    )
    return token


# Backward-compatible alias
generate_token = generate_livekit_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate LiveKit Access Token with Signed Caller Attributes"
    )
    parser.add_argument("--room", type=str, default="test-voice-room", help="Room name to join")
    parser.add_argument("--identity", type=str, default="caller_web", help="Participant identity")
    parser.add_argument("--name", type=str, default="Voice Tester", help="Participant display name")
    parser.add_argument("--hours", type=int, default=24, help="Token validity in hours")
    parser.add_argument(
        "--phone",
        type=str,
        default=None,
        help="Verified caller mobile number embedded in signed JWT attributes",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=settings.deepgram_language or "ar",
        help="Preferred call language ('ar' or 'en')",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="default",
        help="Clinic tenant identifier (default: 'default')",
    )
    parser.add_argument(
        "--branch-id",
        type=str,
        default="main",
        help="Clinic branch identifier (default: 'main')",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Override LiveKit API key (defaults to LIVEKIT_API_KEY in .env)",
    )
    parser.add_argument(
        "--api-secret",
        type=str,
        default=None,
        help="Override LiveKit API secret (defaults to LIVEKIT_API_SECRET in .env)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print only the raw JWT string on stdout",
    )
    args = parser.parse_args(argv)

    try:
        token = generate_livekit_token(
            room_name=args.room,
            identity=args.identity,
            name=args.name,
            valid_hours=args.hours,
            caller_phone=args.phone,
            lang=args.lang,
            tenant_id=args.tenant_id,
            branch_id=args.branch_id,
            api_key=args.api_key,
            api_secret=args.api_secret,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.raw:
        print(token)
        return 0

    masked_phone = (
        f"***{args.phone.strip()[-3:]}"
        if args.phone and len(args.phone.strip()) >= 3
        else "unverified (read-only)"
    )

    print("\n" + "=" * 70)
    print("🎙️  LIVEKIT WEBRTC ACCESS TOKEN GENERATOR")
    print("=" * 70)
    print(f"• LiveKit Server URL : {settings.livekit_url}")
    print(f"• Room Name          : {args.room}")
    print(f"• Participant        : {args.name} ({args.identity})")
    print(f"• Verified Phone     : {masked_phone}")
    print(f"• Language / Tenant  : {args.lang} | {args.tenant_id}/{args.branch_id}")
    print(f"• Validity           : {args.hours} hours")
    print("-" * 70)
    print("📋 Copy this Token into https://agents-playground.livekit.io/ :")
    print("-" * 70)
    print(token)
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
