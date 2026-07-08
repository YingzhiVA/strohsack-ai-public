"""
Memory-management page for the Streamlit web interface (Milestone 2C).

A browser-based *inspector and editor* over what Strohsack durably remembers:
the curated long-term facts (the ``remember()`` tool's output) and the episodic
conversation history. It reads and writes the same SQLite store the CLI
persists to (:class:`~strohsack.memory.store.SQLiteMemoryStore`), so you can run
a few CLI chats and then browse — or prune — everything he's holding onto from
the browser. Good for portfolio demos ("here's what he learned about me") and
for debugging recall.

This page only *manages* memory; it does not chat. The chat page
(:mod:`strohsack.interfaces.web`) now persists to this same store too — each web
thread is saved here and its durable facts injected back — so the notes and
conversations shown here come from both the CLI and the web chat. The two pages
are wired together by :func:`strohsack.interfaces.web.main` via ``st.navigation``.

Every mutation is followed by ``st.rerun()`` so the view reflects the new state
immediately rather than one interaction behind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from strohsack.memory.store import SQLiteMemoryStore

PAGE_ICON = "🐻"


def _format_timestamp(raw: object) -> str:
    """Render a stored ISO-8601 timestamp as a short, friendly local-ish string.

    Falls back to the raw value if it isn't parseable, so a malformed row never
    breaks the page.
    """
    text = str(raw or "")
    try:
        from datetime import datetime

        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def _render_facts(store: "SQLiteMemoryStore") -> None:
    """Durable long-term facts: list, delete one, or wipe them all."""
    st.subheader("🍯 Long-term notes")
    st.caption(
        "Things Strohsack chose to remember about you across conversations — "
        "his curated facts. Deleting one removes it from every future chat."
    )

    facts = store.list_facts()
    if not facts:
        st.info("Strohsack hasn't jotted anything down yet.")
        return

    for entry in facts:
        text = str(entry["fact"])
        text_col, button_col = st.columns([0.9, 0.1])
        text_col.markdown(f"• {text}")
        # The earliest copy's id is a stable, unique key across reruns.
        if button_col.button("🗑", key=f"del-fact-{entry['id']}", help="Forget this note"):
            store.delete_fact(text)
            st.rerun()

    st.divider()
    if st.checkbox("Let me wipe every note", key="confirm-wipe-facts"):
        if st.button("Wipe all long-term notes", type="primary"):
            store.clear_facts(None)
            st.rerun()


def _session_label(session: dict[str, object]) -> str:
    """One-line picker label for a session: name · count · last-updated."""
    sid = str(session["id"])
    name = session["label"] or f"Session {sid[:8]}"
    updated = _format_timestamp(session["updated_at"])
    return f"{name} · {session['message_count']} messages · {updated}"


def _render_sessions(store: "SQLiteMemoryStore") -> None:
    """Episodic history: pick one past conversation to read back, or delete it.

    Only the *selected* conversation's messages are loaded — a rerun (selecting
    another chat, deleting one, or any other widget interaction on the page)
    reads a single session's history rather than every session's.
    """
    st.subheader("💬 Conversation history")
    st.caption("Past chats, most recent first. Pick one to read it back.")

    sessions = store.list_sessions()
    if not sessions:
        st.info("No conversations on record yet.")
        return

    # Map each session id (the selectbox value) to its display label. Ids are
    # unique, so distinct sessions never collide; ``list_sessions`` already
    # orders them most-recent first, so index 0 is the latest chat.
    labels = {str(s["id"]): _session_label(s) for s in sessions}
    session_id = st.selectbox(
        "Choose a conversation",
        list(labels),
        format_func=lambda sid: labels[sid],
        key="session-picker",
    )

    history = store.load_history(session_id)
    if not history:
        st.caption("(empty — no messages)")
    for turn in history:
        avatar = PAGE_ICON if turn["role"] == "assistant" else None
        with st.chat_message(turn["role"], avatar=avatar):
            st.markdown(turn["content"])

    if st.button(
        "Delete this conversation",
        key=f"del-session-{session_id}",
        help="Remove this chat and its messages",
    ):
        store.delete_session(session_id)
        # Forget the picker's remembered choice — it points at the now-deleted
        # session, and Streamlit raises if a selectbox's stored value is no
        # longer one of its options. The next run defaults to the latest chat.
        st.session_state.pop("session-picker", None)
        st.rerun()


def _render_danger_zone(store: "SQLiteMemoryStore") -> None:
    """Full wipe: every long-term note and every stored conversation."""
    st.subheader("🧹 Start completely fresh")
    st.caption(
        "Clear everything — all long-term notes and all stored conversations. "
        "Strohsack wakes up not knowing you at all."
    )
    if st.checkbox("I'm sure — erase Strohsack's whole memory", key="confirm-wipe-all"):
        if st.button("Forget everything", type="primary"):
            store.clear_facts(None)
            for session in store.list_sessions():
                store.delete_session(str(session["id"]))
            st.rerun()


def render(store: "SQLiteMemoryStore") -> None:
    """Render the memory-management page against ``store``.

    Args:
        store: The SQLite-backed memory store to inspect and edit — the same
            database the CLI persists to.
    """
    st.title("🧠 What Strohsack remembers")
    st.caption(
        "A peek inside the bear's head: the notes he keeps and the chats he's "
        "had. Edit freely — it all lives in the same memory the CLI uses."
    )
    _render_facts(store)
    st.divider()
    _render_sessions(store)
    st.divider()
    _render_danger_zone(store)
