"""
LiveKit Token Generator for WebRTC Playground & Manual Testing.

Usage:
    python scripts/generate_token.py
    python scripts/generate_token.py --room test-voice-room --identity caller_01
"""

import argparse
import sys
import os
from pathlib import Path
import datetime

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.agent import voice_agent  # imports clock skew patch
from livekit import api
from src.config import settings


def generate_token(
    room_name: str = "test-voice-room",
    identity: str = "caller_web",
    name: str = "Voice Tester",
    valid_hours: int = 24,
) -> str:
    """Generate a LiveKit JWT token for room join with audio publish/subscribe grants."""
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
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


def main():
    parser = argparse.ArgumentParser(description="Generate LiveKit Access Token for WebRTC Playground")
    parser.add_argument("--room", type=str, default="test-voice-room", help="Room name to join")
    parser.add_argument("--identity", type=str, default="caller_web", help="Participant identity")
    parser.add_argument("--name", type=str, default="Voice Tester", help="Participant display name")
    parser.add_argument("--hours", type=int, default=24, help="Token validity in hours")
    args = parser.parse_args()

    token = generate_token(
        room_name=args.room,
        identity=args.identity,
        name=args.name,
        valid_hours=args.hours,
    )

    print("\n" + "=" * 70)
    print("🎙️  LIVEKIT WEBRTC ACCESS TOKEN GENERATOR")
    print("=" * 70)
    print(f"• LiveKit Server URL : {settings.livekit_url}")
    print(f"• Room Name          : {args.room}")
    print(f"• Participant        : {args.name} ({args.identity})")
    print(f"• Validity           : {args.hours} hours")
    print("-" * 70)
    print("📋 Copy this Token into https://agents-playground.livekit.io/ :")
    print("-" * 70)
    print(token)
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
