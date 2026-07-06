"""
Hello Strohsack — the Phase 0 / Milestone 1A smoke test.

Sends a single greeting to Strohsack and prints his reply. This validates
the whole chain end-to-end: config + system prompt + API client. If this
prints a warm, honey-obsessed bear response, the personality is working.

Run with:  python scripts/hello_strohsack.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly (python scripts/hello_strohsack.py) without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strohsack.conversation.manager import ConversationManager  # noqa: E402
from strohsack.utils.api_client import StrohsackAPIError, StrohsackClient  # noqa: E402
from strohsack.utils.config_loader import ConfigError, load_config  # noqa: E402

PROMPT = "Hello Strohsack! Could you introduce yourself?"


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    conversation = ConversationManager(StrohsackClient(config))

    print(f"You: {PROMPT}\n")
    try:
        reply = conversation.send(PROMPT)
    except StrohsackAPIError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 1

    print(f"Strohsack: {reply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
