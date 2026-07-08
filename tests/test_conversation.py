"""Tests for strohsack.conversation.manager (no live API)."""

from __future__ import annotations

import pytest

from strohsack.conversation.manager import ASSISTANT, USER, ConversationManager


class EchoResponder:
    """Stub responder that records what it was sent and echoes a reply.

    Stands in for the real API client so the manager can be tested without
    network access.
    """

    def __init__(self, reply: str = "Honey!") -> None:
        self.reply = reply
        self.last_messages: list[dict[str, str]] | None = None

    def respond(self, messages: list[dict[str, str]]) -> str:
        self.last_messages = list(messages)
        return self.reply


def test_send_records_user_and_assistant_turns() -> None:
    responder = EchoResponder(reply="Strohsack says hello.")
    manager = ConversationManager(responder)

    reply = manager.send("Hi there")

    assert reply == "Strohsack says hello."
    assert manager.history == [
        {"role": USER, "content": "Hi there"},
        {"role": ASSISTANT, "content": "Strohsack says hello."},
    ]


def test_responder_sees_full_history_ending_with_user_turn() -> None:
    responder = EchoResponder()
    manager = ConversationManager(responder)

    manager.send("first")
    manager.send("second")

    # On the second call the responder should see all four turns, with the
    # latest user message last.
    assert responder.last_messages is not None
    assert len(responder.last_messages) == 3
    assert responder.last_messages[-1] == {"role": USER, "content": "second"}


def test_history_is_a_copy() -> None:
    manager = ConversationManager(EchoResponder())
    manager.send("hi")
    snapshot = manager.history
    snapshot.append({"role": USER, "content": "tampered"})
    assert len(manager.history) == 2  # unaffected by mutating the copy


def test_empty_message_rejected() -> None:
    manager = ConversationManager(EchoResponder())
    with pytest.raises(ValueError):
        manager.send("   ")


def test_reset_clears_history() -> None:
    manager = ConversationManager(EchoResponder())
    manager.send("hi")
    manager.reset()
    assert manager.history == []


class FailingResponder:
    """Responder that raises on the first call, succeeds on the second."""

    def __init__(self) -> None:
        self.calls = 0

    def respond(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("simulated failure")
        return "Honey!"


def test_history_rolled_back_on_responder_failure() -> None:
    responder = FailingResponder()
    manager = ConversationManager(responder)

    with pytest.raises(RuntimeError):
        manager.send("first message")

    # History must be empty — no dangling user turn.
    assert manager.history == []

    # A second send must succeed and produce valid alternating history.
    reply = manager.send("second message")
    assert reply == "Honey!"
    assert manager.history == [
        {"role": USER, "content": "second message"},
        {"role": ASSISTANT, "content": "Honey!"},
    ]


class StreamingEchoResponder:
    """Streaming stub: yields a reply in fixed-size fragments."""

    def __init__(self, reply: str = "Honey honey honey") -> None:
        self.reply = reply
        self.last_messages: list[dict[str, str]] | None = None

    def respond(self, messages: list[dict[str, str]]) -> str:
        self.last_messages = list(messages)
        return self.reply

    def stream_response(self, messages: list[dict[str, str]]):
        self.last_messages = list(messages)
        for word in self.reply.split():
            yield word + " "


def test_send_stream_yields_fragments_and_records_full_reply() -> None:
    responder = StreamingEchoResponder(reply="one two three")
    manager = ConversationManager(responder)

    chunks = list(manager.send_stream("Hi there"))

    assert chunks == ["one ", "two ", "three "]
    # The recorded assistant turn is the concatenation of the fragments.
    assert manager.history == [
        {"role": USER, "content": "Hi there"},
        {"role": ASSISTANT, "content": "one two three "},
    ]


def test_send_stream_sees_history_ending_with_user_turn() -> None:
    responder = StreamingEchoResponder()
    manager = ConversationManager(responder)

    list(manager.send_stream("first"))
    list(manager.send_stream("second"))

    assert responder.last_messages is not None
    assert responder.last_messages[-1] == {"role": USER, "content": "second"}


def test_send_stream_empty_message_rejected_at_call_site() -> None:
    manager = ConversationManager(StreamingEchoResponder())
    # ValueError must fire when send_stream() is called, not when the
    # generator is first iterated (generator functions defer their body).
    with pytest.raises(ValueError):
        manager.send_stream("   ")  # do NOT consume — error must fire here


def test_send_stream_non_streaming_responder_raises_type_error() -> None:
    class PlainResponder:
        def respond(self, messages):
            return "Honey!"

    manager = ConversationManager(PlainResponder())
    with pytest.raises(TypeError, match="stream_response"):
        manager.send_stream("hi")


class FailingStreamResponder:
    """Streaming responder that raises partway through the stream."""

    def respond(self, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("unused")

    def stream_response(self, messages: list[dict[str, str]]):
        yield "partial "
        raise RuntimeError("stream broke")


def test_send_stream_rolls_back_user_turn_on_failure() -> None:
    manager = ConversationManager(FailingStreamResponder())

    with pytest.raises(RuntimeError):
        list(manager.send_stream("a message"))

    # No dangling user turn, and no half-written assistant turn.
    assert manager.history == []


class BaseExceptionStreamResponder:
    """Streaming responder that raises a BaseException (not Exception) mid-stream."""

    def respond(self, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("unused")

    def stream_response(self, messages: list[dict[str, str]]):
        yield "partial "
        raise KeyboardInterrupt  # BaseException subclass, not Exception


def test_send_stream_rolls_back_on_base_exception() -> None:
    manager = ConversationManager(BaseExceptionStreamResponder())

    with pytest.raises(KeyboardInterrupt):
        list(manager.send_stream("a message"))

    # BaseException must also roll back the user turn.
    assert manager.history == []


# --- Persistence (Milestone 2A): manager + MemoryStore integration -----------


class FakeStore:
    """In-memory stand-in for a MemoryStore, scoped to a single session id."""

    def __init__(self, session_id: str, initial: list[dict[str, str]] | None = None) -> None:
        self.session_id = session_id
        self.saved: dict[str, list[dict[str, str]]] = {session_id: list(initial or [])}

    def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self.saved.get(session_id, []))

    def append_messages(self, session_id: str, messages) -> None:
        self.saved.setdefault(session_id, []).extend(dict(m) for m in messages)


def test_store_requires_session_id() -> None:
    with pytest.raises(ValueError):
        ConversationManager(EchoResponder(), store=FakeStore("s1"))


def test_existing_history_is_loaded_on_construction() -> None:
    prior = [
        {"role": USER, "content": "earlier"},
        {"role": ASSISTANT, "content": "honey"},
    ]
    store = FakeStore("s1", initial=prior)
    manager = ConversationManager(EchoResponder(), store=store, session_id="s1")
    assert manager.history == prior


def test_loaded_history_is_sent_to_responder() -> None:
    store = FakeStore("s1", initial=[{"role": USER, "content": "earlier"},
                                     {"role": ASSISTANT, "content": "honey"}])
    responder = EchoResponder()
    manager = ConversationManager(responder, store=store, session_id="s1")

    manager.send("now")

    # The responder should see the resumed turns plus the new user message.
    assert responder.last_messages is not None
    assert responder.last_messages[0] == {"role": USER, "content": "earlier"}
    assert responder.last_messages[-1] == {"role": USER, "content": "now"}


def test_send_persists_the_completed_turn() -> None:
    store = FakeStore("s1")
    manager = ConversationManager(EchoResponder(reply="Honey!"), store=store, session_id="s1")

    manager.send("hi")

    assert store.saved["s1"] == [
        {"role": USER, "content": "hi"},
        {"role": ASSISTANT, "content": "Honey!"},
    ]


def test_failed_send_persists_nothing() -> None:
    store = FakeStore("s1")
    manager = ConversationManager(FailingResponder(), store=store, session_id="s1")

    with pytest.raises(RuntimeError):
        manager.send("doomed")

    # Nothing should have been written when the responder failed.
    assert store.saved["s1"] == []


def test_send_stream_persists_full_reply() -> None:
    store = FakeStore("s1")
    manager = ConversationManager(
        StreamingEchoResponder(reply="one two"), store=store, session_id="s1"
    )

    list(manager.send_stream("hi"))

    assert store.saved["s1"] == [
        {"role": USER, "content": "hi"},
        {"role": ASSISTANT, "content": "one two "},
    ]


def test_failed_stream_persists_nothing() -> None:
    store = FakeStore("s1")
    manager = ConversationManager(FailingStreamResponder(), store=store, session_id="s1")

    with pytest.raises(RuntimeError):
        list(manager.send_stream("a message"))

    assert store.saved["s1"] == []
