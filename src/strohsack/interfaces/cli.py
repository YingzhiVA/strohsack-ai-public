"""
Terminal chat interface for Strohsack AI.

A simple read-reply-print loop: type a message, Strohsack replies. Type
``exit``, ``quit``, or press Ctrl-C / Ctrl-D to leave.

Conversations persist across runs (Milestone 2A): by default Strohsack resumes
your most recent session, so he remembers what you talked about last time.
Start fresh with ``--new``, or type ``forget`` mid-chat to wipe the current
session's memory.

Run with:  python -m strohsack.interfaces.cli  [--new]
"""

from __future__ import annotations

import argparse
import sys

from strohsack.conversation.manager import ConversationManager
from strohsack.interfaces import farewell, greeting
from strohsack.memory.store import SQLiteMemoryStore
from strohsack.utils.api_client import (
    StrohsackAPIError,
    StrohsackClient,
    Usage,
    estimate_cost,
    estimate_uncached_cost,
)
from strohsack.utils.config_loader import ConfigError, load_config

EXIT_COMMANDS = {"exit", "quit", "bye"}
FORGET_COMMANDS = {"forget"}
STATS_COMMANDS = {"stats"}
CONSOLIDATE_COMMANDS = {"consolidate", "tidy"}


def _format_turn_usage(usage: Usage, model: str) -> str:
    """One-line per-turn token/cache readout (shown under --stats)."""
    parts = (
        f"in {usage.input_tokens} · cached {usage.cache_read_tokens} · "
        f"new-cache {usage.cache_write_tokens} · out {usage.output_tokens}"
    )
    cost = estimate_cost(usage, model)
    if cost is None:
        return f"[usage] {parts}"
    uncached = estimate_uncached_cost(usage, model) or cost
    return f"[usage] {parts}  (~${cost:.4f}, saved ~${uncached - cost:.4f})"


def _format_session_stats(usage: Usage, model: str) -> str:
    """Multi-line session token/cache summary (the `stats` command)."""
    lines = [
        "[Strohsack's ledger this session]",
        f"  input : {usage.input_tokens} uncached · {usage.cache_read_tokens} "
        f"from cache · {usage.cache_write_tokens} written to cache",
        f"  output: {usage.output_tokens}",
        f"  cache hit rate: {usage.cache_hit_rate * 100:.0f}% "
        "(of cacheable input served from cache)",
    ]
    cost = estimate_cost(usage, model)
    if cost is not None:
        uncached = estimate_uncached_cost(usage, model) or cost
        lines.append(
            f"  estimated cost: ~${cost:.4f}  (≈${uncached:.4f} uncached → "
            f"saved ~${uncached - cost:.4f}, Sonnet 4.6 rates)"
        )
    return "\n".join(lines)


def run(new_session: bool = False, show_stats: bool = False) -> int:
    """Start the interactive chat loop.

    Args:
        new_session: When True, start a fresh session instead of resuming the
            most recent one.
        show_stats: When True, print a per-turn token/cache usage line after each
            reply. The ``stats`` command shows the session summary regardless.

    Returns:
        Process exit code (0 on clean exit, 1 on configuration error).
    """
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    store = SQLiteMemoryStore()

    if new_session:
        session_id = store.create_session()
    else:
        session_id = store.latest_session_id() or store.create_session()

    # The same store backs episodic history (via the manager) and durable facts
    # (via the client's remember() tool + fact injection).
    client = StrohsackClient(config, fact_store=store, session_id=session_id)
    conversation = ConversationManager(client, store=store, session_id=session_id)
    resumed = not new_session and bool(conversation.history)

    print("=" * 60)
    print("  Strohsack the Bear")
    print("  commands: exit · forget (wipe chat) · tidy (consolidate notes) · stats")
    print("=" * 60)
    if resumed:
        print("\n[Strohsack stirs from his nap — he remembers your last chat.]")
    print(f"\nStrohsack: {greeting()}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\nStrohsack: {farewell()}")
            return 0

        if not user_input:
            continue
        if user_input.lower() in EXIT_COMMANDS:
            print(f"\nStrohsack: {farewell()}")
            return 0
        if user_input.lower() in FORGET_COMMANDS:
            conversation.reset()
            store.clear_session(session_id)
            store.clear_facts(session_id)
            print(
                "\n[Strohsack yawns. This chat — and the notes he took during "
                "it — are gone now. Anything he'd already tidied into long-term "
                "memory stays.]\n"
            )
            continue
        if user_input.lower() in STATS_COMMANDS:
            print(f"\n{_format_session_stats(client.session_usage, config.model)}\n")
            continue
        if user_input.lower() in CONSOLIDATE_COMMANDS:
            try:
                before, after = client.consolidate_facts()
            except StrohsackAPIError as exc:
                print(f"\n[Strohsack couldn't tidy his notes — {exc}]\n", file=sys.stderr)
                continue
            if before < 2:
                print("\n[Strohsack barely has any notes yet — nothing to tidy.]\n")
            elif after < before:
                print(f"\n[Strohsack tidied his notes: {before} → {after}.]\n")
            else:
                print(f"\n[Strohsack looked over his {before} notes; they're already tidy.]\n")
            continue

        try:
            reply = conversation.send(user_input)
        except StrohsackAPIError as exc:
            print(f"\n[Strohsack is napping — the API call failed: {exc}]\n", file=sys.stderr)
            continue

        print(f"\nStrohsack: {reply}\n")
        if show_stats:
            print(f"{_format_turn_usage(client.last_usage, config.model)}\n")


def main() -> None:
    """Console entry point."""
    parser = argparse.ArgumentParser(description="Chat with Strohsack the Bear.")
    parser.add_argument(
        "--new",
        action="store_true",
        help="Start a fresh session instead of resuming your last conversation.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print per-turn token/cache usage after each reply.",
    )
    args = parser.parse_args()
    sys.exit(run(new_session=args.new, show_stats=args.stats))


if __name__ == "__main__":
    main()
