"""
Streamlit web interface for Strohsack AI.

A browser-based chat reusing the same memory-wired core as the CLI
(:class:`~strohsack.conversation.manager.ConversationManager` +
:class:`~strohsack.utils.api_client.StrohsackClient`). Replies stream in token
by token (rendered into a single placeholder with a typing cursor) for a live
typing effect — nicer for demos.

Memory (Milestone 2): each browser session gets a **fresh episodic thread**
(a new persisted session in the shared SQLite store), but Strohsack still recalls
the human through **durable facts**, which are cross-session — injected into the
prompt each turn and saved via his ``remember()`` tool, exactly as in the CLI.
Past threads remain browsable on the 🧠 Memory page. (Per-guest isolation is a
later milestone; today this is single-user, so a fresh thread per load keeps the
demo clean while the long-term notes carry the "he remembers me" story.)

Run with:  streamlit run src/strohsack/interfaces/web.py

Streamlit reruns this whole script on every interaction, so the conversation
(and the client that backs it) is kept in ``st.session_state`` to survive
across reruns — created once per browser session, not once per rerun.
"""

from __future__ import annotations

import streamlit as st

from strohsack.conversation.manager import ConversationManager
from strohsack.interfaces import farewell, greeting, memory_ui
from strohsack.memory.store import SQLiteMemoryStore
from strohsack.utils.api_client import StrohsackClient
from strohsack.utils.config_loader import Config, ConfigError, load_config

PAGE_TITLE = "Strohsack the Bear"
PAGE_ICON = "🐻"

# Shown when the API errors mid-conversation, in Strohsack's voice.
API_ERROR_NOTICE = "*Strohsack is napping — he couldn't be roused just now. Try again in a moment.*"


@st.cache_resource
def _load_config() -> Config:
    """Resolve application config once, shared across reruns.

    Raises :class:`~strohsack.utils.config_loader.ConfigError` if
    configuration is missing so that nothing invalid is cached — fixing
    ``.env`` and reloading the browser recovers without a server restart.
    The config is immutable and conversation-independent, so caching it (and
    rebuilding the per-session client from it) is safe.
    """
    return load_config()


@st.cache_resource
def _build_store() -> SQLiteMemoryStore:
    """Open the persistent memory store once, shared across reruns and pages.

    Backs both the chat (episodic history + durable facts) and the 🧠 Memory
    page (:mod:`strohsack.interfaces.memory_ui`), which inspect and edit the
    same SQLite database the CLI persists to. :class:`SQLiteMemoryStore` is
    built for cross-thread reuse (a lock serializes access), so caching one
    instance across Streamlit's reruns is safe.
    """
    return SQLiteMemoryStore()


def _start_conversation() -> ConversationManager:
    """Build a fresh, memory-wired conversation backed by a new session.

    Mirrors the CLI's wiring (:func:`strohsack.interfaces.cli.run`): a new
    episodic session in the shared store, a client that injects the human's
    durable facts and exposes ``remember()`` (``fact_store`` + ``session_id``),
    and a manager that persists each completed turn to that session. Durable
    facts are cross-session, so a fresh thread still recalls the human.

    Raises:
        ConfigError: Propagated from :func:`_load_config` if configuration is
            missing or invalid.
    """
    store = _build_store()
    session_id = store.create_session()
    client = StrohsackClient(_load_config(), fact_store=store, session_id=session_id)
    return ConversationManager(client, store=store, session_id=session_id)


def _get_conversation() -> ConversationManager:
    """Return this browser session's conversation, creating it on first use.

    Kept in ``st.session_state`` (not the resource cache) so it's built once per
    browser session — a fresh episodic thread per visitor — rather than once per
    rerun. "New nap" replaces it with another fresh session.

    Raises:
        ConfigError: Propagated from :func:`_start_conversation` if
            configuration is missing or invalid.
    """
    if "conversation" not in st.session_state:
        st.session_state.conversation = _start_conversation()
    return st.session_state.conversation


def _session_greeting() -> str:
    """The greeting for this session, picked once and held across reruns.

    Streamlit reruns the whole script on every interaction, so we stash the
    chosen variant in ``session_state`` — otherwise it would re-roll (and
    visibly flicker) on every keystroke. Cleared by "New nap" so a reset
    session gets a fresh opener.
    """
    if "greeting" not in st.session_state:
        st.session_state.greeting = greeting()
    return st.session_state.greeting


def _render_history(conversation: ConversationManager) -> None:
    """Replay the conversation so far as chat bubbles."""
    # The greeting isn't part of the model history; show it as the opener.
    with st.chat_message("assistant", avatar=PAGE_ICON):
        st.markdown(_session_greeting())
    for turn in conversation.history:
        avatar = PAGE_ICON if turn["role"] == "assistant" else None
        with st.chat_message(turn["role"], avatar=avatar):
            st.markdown(turn["content"])


def _chat_page() -> None:
    """Render the Strohsack chat page."""
    st.title(f"{PAGE_ICON} Strohsack the Bear")
    st.caption("A lazy, honey-obsessed bear who learns things in his dreams.")

    try:
        conversation = _get_conversation()
    except ConfigError as exc:
        st.error(f"**Configuration error:** {exc}")
        st.stop()
        return  # unreachable; satisfies type checkers

    with st.sidebar:
        if st.button("🌙 New nap (reset chat)", use_container_width=True):
            # Start a genuinely fresh episodic thread (new persisted session),
            # not just an in-memory clear: the old thread stays in the store
            # (browsable on the Memory page) and durable facts carry over, so
            # he still remembers the human.
            st.session_state.conversation = _start_conversation()
            st.session_state.said_goodbye = False
            # Drop the held lines so the fresh session re-rolls a new opener
            # (and a new farewell when the guest next leaves).
            st.session_state.pop("greeting", None)
            st.session_state.pop("farewell", None)
            st.rerun()
        if st.button("👋 Say goodbye", use_container_width=True):
            st.session_state.said_goodbye = True
            # Pick the farewell once, here, so it stays put across reruns.
            st.session_state.farewell = farewell()
            st.rerun()

    _render_history(conversation)

    # Once the guest has said goodbye, show Strohsack's farewell and close the
    # input. "New nap" brings him back. (There's no server process to kill
    # from the browser — this is the web equivalent of the CLI's exit.)
    if st.session_state.get("said_goodbye"):
        # Stored by the "Say goodbye" button; fall back in case the flag is
        # set without it (e.g. across an upgrade).
        line = st.session_state.get("farewell") or farewell()
        with st.chat_message("assistant", avatar=PAGE_ICON):
            st.markdown(f"*{line}*")
        st.chat_input("Strohsack is napping — start a new nap to wake him.", disabled=True)
        return

    user_input = st.chat_input("Say something to Strohsack...")
    if not user_input:
        return

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant", avatar=PAGE_ICON):
        placeholder = st.empty()
        reply = ""
        try:
            # Drive the stream ourselves rather than via st.write_stream: we
            # update a single placeholder with the accumulated text plus a
            # cursor, which renders far more smoothly than write_stream's
            # per-chunk re-render and shows tokens as they actually arrive.
            for chunk in conversation.send_stream(user_input):
                reply += chunk
                placeholder.markdown(reply + " ▌")
            placeholder.markdown(reply)
        except Exception:
            # Catch any exception (API failure, network drop, unexpected error)
            # so Streamlit's crash page is never shown for a failed reply.
            placeholder.markdown(API_ERROR_NOTICE)


def _memory_page() -> None:
    """Render the memory-management page over the persistent store."""
    memory_ui.render(_build_store())


def main() -> None:
    """Route between the chat and memory pages via the sidebar nav.

    ``st.navigation`` renders a sidebar entry per page and runs the selected
    one. ``set_page_config`` is called once here (not inside the pages) so the
    title/icon are set before either page renders.
    """
    st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON)
    nav = st.navigation(
        [
            st.Page(_chat_page, title="Chat", icon="🐻", default=True),
            st.Page(_memory_page, title="Memory", icon="🧠"),
        ]
    )
    nav.run()


if __name__ == "__main__":
    main()
