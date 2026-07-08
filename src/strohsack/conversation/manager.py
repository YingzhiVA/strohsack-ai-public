"""
Conversation management for Strohsack AI.

Holds the message history for a single session and orchestrates turns
between the user and Strohsack. By default history lives only for the lifetime
of the object; pass a :class:`~strohsack.memory.store.MemoryStore` and a
``session_id`` to persist it across restarts (Milestone 2A) — the manager loads
prior history on construction and saves each completed turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

    from strohsack.memory.store import MemoryStore

USER = "user"
ASSISTANT = "assistant"


class Responder(Protocol):
    """Anything that can turn a message history into a reply.

    :class:`~strohsack.utils.api_client.StrohsackClient` satisfies this;
    tests can pass a stub.
    """

    def respond(self, messages: list[dict[str, str]]) -> str: ...


class StreamingResponder(Responder, Protocol):
    """A :class:`Responder` that can also stream a reply in fragments.

    Required by :meth:`ConversationManager.send_stream`.
    :class:`~strohsack.utils.api_client.StrohsackClient` satisfies this.
    """

    def stream_response(self, messages: list[dict[str, str]]) -> "Iterator[str]": ...


class ConversationManager:
    """Tracks a single session's message history and produces replies.

    Args:
        responder: Object that generates a reply from message history.
        store: Optional persistent backend. When given together with
            ``session_id``, prior history is loaded on construction and each
            completed turn is saved. When ``None`` (the default), history is
            in-memory only and lost when the object is discarded.
        session_id: The session to load from and persist to in ``store``.
            Required whenever ``store`` is given.

    Raises:
        ValueError: If ``store`` is given without ``session_id``.
    """

    def __init__(
        self,
        responder: Responder,
        store: "MemoryStore | None" = None,
        session_id: str | None = None,
    ) -> None:
        if store is not None and session_id is None:
            raise ValueError("session_id is required when a store is provided.")
        self._responder = responder
        self._store = store
        self._session_id = session_id
        self._history: list[dict[str, str]] = []
        if store is not None and session_id is not None:
            self._history = store.load_history(session_id)

    @property
    def history(self) -> list[dict[str, str]]:
        """A copy of the conversation so far (oldest first)."""
        return list(self._history)

    def send(self, user_message: str) -> str:
        """Record a user message, get Strohsack's reply, and record it too.

        Args:
            user_message: The user's input text.

        Returns:
            Strohsack's reply.

        Raises:
            ValueError: If ``user_message`` is empty or whitespace.
        """
        text = user_message.strip()
        if not text:
            raise ValueError("Cannot send an empty message.")

        user_turn = {"role": USER, "content": text}
        self._history.append(user_turn)
        try:
            reply = self._responder.respond(self._history)
        except Exception:
            self._history.pop()
            raise
        assistant_turn = {"role": ASSISTANT, "content": reply}
        self._history.append(assistant_turn)
        self._persist([user_turn, assistant_turn])
        return reply

    def send_stream(self, user_message: str) -> "Iterator[str]":
        """Like :meth:`send`, but stream the reply in fragments.

        Records the user turn, yields fragments of Strohsack's reply as the
        responder produces them, then records the assembled reply as the
        assistant turn once streaming finishes.

        The responder must be a :class:`StreamingResponder`. As with
        :meth:`send`, the user turn is rolled back if streaming raises before
        completing, leaving history valid for the next attempt.

        ``ValueError`` is raised immediately (not deferred to first iteration)
        so the call site sees the error at the right stack frame.

        Args:
            user_message: The user's input text.

        Yields:
            Successive fragments of Strohsack's reply.

        Raises:
            ValueError: If ``user_message`` is empty or whitespace.
        """
        text = user_message.strip()
        if not text:
            raise ValueError("Cannot send an empty message.")
        if not hasattr(self._responder, "stream_response"):
            raise TypeError(
                f"{type(self._responder).__name__} does not implement stream_response(); "
                "pass a StreamingResponder to use send_stream()."
            )
        return self._stream(text)

    def _stream(self, text: str) -> "Iterator[str]":
        """Inner generator for :meth:`send_stream` (validation already done)."""
        responder = cast("StreamingResponder", self._responder)
        user_turn = {"role": USER, "content": text}
        self._history.append(user_turn)
        parts: list[str] = []
        try:
            for chunk in responder.stream_response(self._history):
                parts.append(chunk)
                yield chunk
        except BaseException:
            # BaseException (not just Exception) so Streamlit's RerunException
            # and GeneratorExit don't leave an orphaned user turn in history.
            self._history.pop()
            raise
        assistant_turn = {"role": ASSISTANT, "content": "".join(parts)}
        self._history.append(assistant_turn)
        self._persist([user_turn, assistant_turn])

    def reset(self) -> None:
        """Clear the in-memory conversation history.

        This only affects this object's working history; it does not delete
        anything from the persistent store. To forget a stored conversation,
        clear it through the store (see the CLI ``forget`` command).
        """
        self._history.clear()

    @property
    def session_id(self) -> str | None:
        """The persistent session id this manager reads from and writes to."""
        return self._session_id

    def _persist(self, messages: list[dict[str, str]]) -> None:
        """Save a completed turn to the store, if one is configured."""
        if self._store is not None and self._session_id is not None:
            self._store.append_messages(self._session_id, messages)
