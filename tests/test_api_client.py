"""Tests for strohsack.utils.api_client (no live API).

All tests mock the Anthropic SDK client so nothing hits the network. The client
has two paths: a plain single-call path (no fact store) and the M2C memory path
(fact store -> inject facts + remember() tool via the beta tool runner).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from strohsack.utils.api_client import (
    StrohsackAPIError,
    StrohsackClient,
    Usage,
    estimate_cost,
    estimate_uncached_cost,
)
from strohsack.utils.config_loader import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config() -> Config:
    return Config(
        api_key="test-key",
        model="claude-test",
        max_tokens=100,
        system_prompt="You are a bear.",
    )


def _fake_message(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def _usage(inp: int = 0, read: int = 0, write: int = 0, out: int = 0) -> SimpleNamespace:
    """An SDK-shaped usage object (the field names the API returns)."""
    return SimpleNamespace(
        input_tokens=inp,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
        output_tokens=out,
    )


class FakeFactStore:
    """In-memory stand-in for the durable-fact backend."""

    def __init__(self, facts: list[str] | None = None) -> None:
        self._facts = list(facts or [])
        self.added: list[tuple[str, str | None]] = []
        self.add_result = True

    def load_facts(self) -> list[str]:
        return list(self._facts)

    def add_fact(self, fact: str, session_id: str | None = None) -> bool:
        self.added.append((fact, session_id))
        return self.add_result

    def replace_facts(self, facts: list[str]) -> None:
        self._facts = list(facts)
        self.replaced = list(facts)


def _client(*, fact_store=None, session_id=None) -> tuple[StrohsackClient, MagicMock]:
    """Build a StrohsackClient with a mocked Anthropic client; return both."""
    with patch("strohsack.utils.api_client.Anthropic") as MockAnthropic:
        mock = MockAnthropic.return_value
        client = StrohsackClient(_config(), fact_store=fact_store, session_id=session_id)
        client._client = mock
    return client, mock


def _runner(*turns: MagicMock) -> MagicMock:
    """A fake tool runner that yields the given assistant messages when iterated.

    respond() now does ``list(runner)`` (not ``until_done()``) so it can gather
    text from every round of the loop.
    """
    runner = MagicMock()
    runner.__iter__ = MagicMock(return_value=iter(turns))
    return runner


# ---------------------------------------------------------------------------
# Plain path (no fact store): respond()
# ---------------------------------------------------------------------------


class TestRespondPlain:
    def test_returns_text(self) -> None:
        client, mock = _client()
        mock.messages.create.return_value = _fake_message("Honey!")
        assert client.respond([{"role": "user", "content": "hi"}]) == "Honey!"

    def test_uses_plain_create_not_tool_runner(self) -> None:
        client, mock = _client()
        mock.messages.create.return_value = _fake_message("ok")
        client.respond([{"role": "user", "content": "hi"}])
        mock.messages.create.assert_called_once()
        mock.beta.messages.tool_runner.assert_not_called()

    def test_system_is_cache_controlled_persona_block(self) -> None:
        client, mock = _client()
        mock.messages.create.return_value = _fake_message("ok")
        client.respond([{"role": "user", "content": "hi"}])
        system = mock.messages.create.call_args.kwargs["system"]
        # A single persona block carrying the cache_control breakpoint, no facts.
        assert system == [
            {
                "type": "text",
                "text": "You are a bear.",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_raises_on_empty_text(self) -> None:
        client, mock = _client()
        block = MagicMock()
        block.type = "text"
        block.text = "   "
        msg = MagicMock()
        msg.content = [block]
        mock.messages.create.return_value = msg
        with pytest.raises(StrohsackAPIError, match="empty response"):
            client.respond([{"role": "user", "content": "hi"}])

    def test_wraps_exception(self) -> None:
        client, mock = _client()
        mock.messages.create.side_effect = RuntimeError("network gone")
        with pytest.raises(StrohsackAPIError, match="Anthropic API request failed"):
            client.respond([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Memory path (fact store): respond()
# ---------------------------------------------------------------------------


class TestRespondWithMemory:
    def test_uses_tool_runner_and_returns_text(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        mock.beta.messages.tool_runner.return_value = _runner(_fake_message("Hello friend!"))

        assert client.respond([{"role": "user", "content": "hi"}]) == "Hello friend!"
        mock.beta.messages.tool_runner.assert_called_once()
        mock.messages.create.assert_not_called()

    def test_collects_text_across_rounds_when_final_message_empty(self) -> None:
        """Regression: Strohsack replies *and* calls remember() in round one, so
        his words are in the tool-use message and the final post-tool message has
        no text. respond() must gather text from all rounds, not just the last."""
        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        reply_round = _fake_message("Oh, Scotland — Strohsack dreams of it.")
        empty_final = MagicMock()
        empty_final.content = []  # end_turn with no text after the tool result
        mock.beta.messages.tool_runner.return_value = _runner(reply_round, empty_final)

        reply = client.respond([{"role": "user", "content": "I love Scotland"}])
        assert reply == "Oh, Scotland — Strohsack dreams of it."

    def test_concatenates_text_from_every_round(self) -> None:
        """When the model emits text in BOTH the tool-use round and the final
        post-tool round, respond() joins them (matching stream_response, which
        yields each round). This pins the multi-round gathering against a
        regression to reading only the first or last turn."""
        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        round1 = _fake_message("Noting that down... ")
        round2 = _fake_message("done, Strohsack won't forget!")
        mock.beta.messages.tool_runner.return_value = _runner(round1, round2)

        reply = client.respond([{"role": "user", "content": "remember this"}])
        assert reply == "Noting that down... done, Strohsack won't forget!"

    def test_injects_facts_after_cached_persona_and_rules_blocks(self) -> None:
        store = FakeFactStore(["Name is Yingzhi", "Loves oak honey"])
        client, mock = _client(fact_store=store, session_id="s1")
        mock.beta.messages.tool_runner.return_value = _runner(_fake_message("ok"))

        client.respond([{"role": "user", "content": "hi"}])

        system = mock.beta.messages.tool_runner.call_args.kwargs["system"]
        # Persona block first, then the static memory rules — both cached — and
        # facts in a block AFTER the last breakpoint (no cache_control) so saving
        # a fact won't invalidate the cached prefix.
        assert system[0]["text"] == "You are a bear."
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert "Memory rules" in system[1]["text"]
        assert system[1]["cache_control"] == {"type": "ephemeral"}
        assert "- Name is Yingzhi" in system[2]["text"]
        assert "- Loves oak honey" in system[2]["text"]
        assert "cache_control" not in system[2]

    def test_no_facts_block_when_store_empty(self) -> None:
        client, mock = _client(fact_store=FakeFactStore([]), session_id="s1")
        mock.beta.messages.tool_runner.return_value = _runner(_fake_message("ok"))

        client.respond([{"role": "user", "content": "hi"}])
        system = mock.beta.messages.tool_runner.call_args.kwargs["system"]
        # Persona + memory rules, but no facts block appended.
        assert len(system) == 2
        assert system[0]["text"] == "You are a bear."
        assert "Memory rules" in system[1]["text"]

    def test_plain_path_has_no_memory_rules_block(self) -> None:
        """Without a fact store (eval, tests) the system prompt is untouched —
        the never-store rules only ship when durable memory is actually on."""
        client, mock = _client()
        mock.messages.create.return_value = _fake_message("ok")
        client.respond([{"role": "user", "content": "hi"}])
        system = mock.messages.create.call_args.kwargs["system"]
        assert len(system) == 1

    def test_remember_tool_is_offered(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        mock.beta.messages.tool_runner.return_value = _runner(_fake_message("ok"))

        client.respond([{"role": "user", "content": "hi"}])
        tools = mock.beta.messages.tool_runner.call_args.kwargs["tools"]
        assert len(tools) == 1

    def test_raises_when_no_round_has_text(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        empty = MagicMock()
        empty.content = []
        mock.beta.messages.tool_runner.return_value = _runner(empty)
        with pytest.raises(StrohsackAPIError, match="empty response"):
            client.respond([{"role": "user", "content": "hi"}])

    def test_wraps_exception_raised_mid_iteration(self) -> None:
        """The real tool_runner makes API calls lazily *during* iteration, so a
        network error surfaces from __next__, not __iter__. respond() collects
        each round as it arrives, which must still wrap a failure raised
        mid-loop."""

        def exploding_rounds():
            yield _fake_message("partial thought... ")
            raise RuntimeError("dropped mid-loop")

        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        runner = MagicMock()
        runner.__iter__ = MagicMock(return_value=exploding_rounds())
        mock.beta.messages.tool_runner.return_value = runner
        with pytest.raises(StrohsackAPIError, match="Anthropic API request failed"):
            client.respond([{"role": "user", "content": "hi"}])

    def test_records_usage_of_rounds_completed_before_a_mid_loop_failure(self) -> None:
        """Tokens from rounds that finished before the failure were really spent,
        so they must still land on the session ledger (recorded in a finally)."""
        round1 = _fake_message("partial thought... ")
        round1.usage = _usage(inp=100, out=10)

        def exploding_rounds():
            yield round1
            raise RuntimeError("dropped mid-loop")

        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        runner = MagicMock()
        runner.__iter__ = MagicMock(return_value=exploding_rounds())
        mock.beta.messages.tool_runner.return_value = runner
        with pytest.raises(StrohsackAPIError):
            client.respond([{"role": "user", "content": "hi"}])
        assert client.session_usage == Usage(input_tokens=100, output_tokens=10)


# ---------------------------------------------------------------------------
# The remember() tool itself
# ---------------------------------------------------------------------------


class TestRememberTool:
    def test_saves_fact_with_session_id(self) -> None:
        store = FakeFactStore()
        client, _ = _client(fact_store=store, session_id="s1")
        result = client._remember_tool.call({"note": "Adopted a cat named Biscuit"})
        assert store.added == [("Adopted a cat named Biscuit", "s1")]
        assert "Saved" in result

    def test_duplicate_fact_reports_already_known(self) -> None:
        store = FakeFactStore()
        store.add_result = False  # store rejects as duplicate
        client, _ = _client(fact_store=store, session_id="s1")
        result = client._remember_tool.call({"note": "Loves honey"})
        assert "Already" in result

    def test_no_tool_built_without_fact_store(self) -> None:
        client, _ = _client()
        assert client._remember_tool is None

    def test_never_store_note_is_rejected_before_persistence(self) -> None:
        """The deterministic guard (safety.md categories 4-5) runs in the write
        path: a credential-shaped note never reaches add_fact, and the tool
        result tells the model it wasn't saved — without crashing the turn."""
        store = FakeFactStore()
        client, _ = _client(fact_store=store, session_id="s1")
        result = client._remember_tool.call({"note": "Her password is hunter2"})
        assert store.added == []
        assert "Not saved" in result

    def test_card_number_note_is_rejected(self) -> None:
        store = FakeFactStore()
        client, _ = _client(fact_store=store, session_id="s1")
        result = client._remember_tool.call({"note": "Card number 4111 1111 1111 1111"})
        assert store.added == []
        assert "Not saved" in result

    def test_ordinary_note_still_saves_with_guard_in_place(self) -> None:
        store = FakeFactStore()
        client, _ = _client(fact_store=store, session_id="s1")
        result = client._remember_tool.call({"note": "Always forgets her passwords"})
        assert store.added == [("Always forgets her passwords", "s1")]
        assert "Saved" in result


# ---------------------------------------------------------------------------
# Streaming (both paths)
# ---------------------------------------------------------------------------


class TestStreamResponse:
    def test_plain_path_yields_chunks(self) -> None:
        client, mock = _client()
        stream_obj = MagicMock()
        stream_obj.text_stream = iter(["Hel", "lo"])
        mock.messages.stream.return_value.__enter__.return_value = stream_obj

        chunks = list(client.stream_response([{"role": "user", "content": "hi"}]))
        assert "".join(chunks) == "Hello"
        mock.beta.messages.tool_runner.assert_not_called()

    def test_memory_path_yields_across_rounds(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(["x"]), session_id="s1")
        stream1 = MagicMock()
        stream1.text_stream = iter(["I'll note that... "])
        stream2 = MagicMock()
        stream2.text_stream = iter(["done!"])
        runner = MagicMock()
        runner.__iter__ = MagicMock(return_value=iter([stream1, stream2]))
        mock.beta.messages.tool_runner.return_value = runner

        chunks = list(client.stream_response([{"role": "user", "content": "hi"}]))
        assert "".join(chunks) == "I'll note that... done!"

    def test_wraps_exception_during_streaming(self) -> None:
        client, mock = _client()

        def bad_stream() -> Iterator[str]:
            yield "partial"
            raise RuntimeError("dropped")

        stream_obj = MagicMock()
        stream_obj.text_stream = bad_stream()
        mock.messages.stream.return_value.__enter__.return_value = stream_obj

        gen = client.stream_response([{"role": "user", "content": "hi"}])
        assert next(gen) == "partial"
        with pytest.raises(StrohsackAPIError, match="Anthropic API request failed"):
            next(gen)


# ---------------------------------------------------------------------------
# Token / cache usage tracking
# ---------------------------------------------------------------------------


class TestUsageTracking:
    def test_plain_path_records_usage(self) -> None:
        client, mock = _client()
        msg = _fake_message("ok")
        msg.usage = _usage(inp=10, read=2288, out=18)
        mock.messages.create.return_value = msg

        client.respond([{"role": "user", "content": "hi"}])
        assert client.last_usage == Usage(input_tokens=10, cache_read_tokens=2288, output_tokens=18)
        assert client.session_usage == client.last_usage

    def test_session_usage_accumulates_across_turns(self) -> None:
        client, mock = _client()
        cold = _fake_message("a")
        cold.usage = _usage(inp=10, write=2288, out=5)  # first turn writes the cache
        warm = _fake_message("b")
        warm.usage = _usage(inp=10, read=2288, out=7)  # second turn reads it
        mock.messages.create.side_effect = [cold, warm]

        client.respond([{"role": "user", "content": "hi"}])
        client.respond([{"role": "user", "content": "again"}])
        assert client.session_usage == Usage(
            input_tokens=20, cache_read_tokens=2288, cache_write_tokens=2288, output_tokens=12
        )
        assert client.last_usage == Usage(input_tokens=10, cache_read_tokens=2288, output_tokens=7)

    def test_memory_path_sums_usage_across_rounds(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(), session_id="s1")
        r1 = _fake_message("noting")
        r1.usage = _usage(inp=10, write=2288, out=5)
        r2 = _fake_message("done")
        r2.usage = _usage(inp=5, read=2288, out=8)
        mock.beta.messages.tool_runner.return_value = _runner(r1, r2)

        client.respond([{"role": "user", "content": "hi"}])
        assert client.last_usage == Usage(
            input_tokens=15, cache_read_tokens=2288, cache_write_tokens=2288, output_tokens=13
        )

    def test_missing_usage_field_records_zero(self) -> None:
        # A response object without a real usage block must not crash the recorder.
        client, mock = _client()
        mock.messages.create.return_value = _fake_message("ok")  # .usage is a bare mock
        client.respond([{"role": "user", "content": "hi"}])
        assert client.last_usage == Usage()


class TestUsageMath:
    def test_add(self) -> None:
        assert Usage(1, 2, 3, 4) + Usage(10, 20, 30, 40) == Usage(11, 22, 33, 44)

    def test_total_input(self) -> None:
        u = Usage(input_tokens=10, cache_read_tokens=2288, cache_write_tokens=100)
        assert u.total_input == 2398

    def test_cache_hit_rate(self) -> None:
        assert Usage(cache_read_tokens=900, cache_write_tokens=100).cache_hit_rate == 0.9
        assert Usage().cache_hit_rate == 0.0  # nothing cacheable -> 0, no ZeroDivision

    def test_estimate_cost_sonnet(self) -> None:
        assert estimate_cost(Usage(input_tokens=1_000_000), "claude-sonnet-4-6") == pytest.approx(
            3.0
        )
        assert estimate_cost(Usage(output_tokens=1_000_000), "claude-sonnet-4-6") == pytest.approx(
            15.0
        )

    def test_estimate_cost_unknown_model_is_none(self) -> None:
        assert estimate_cost(Usage(input_tokens=100), "some-other-model") is None
        assert estimate_uncached_cost(Usage(input_tokens=100), "some-other-model") is None

    def test_cache_read_is_cheaper_than_uncached(self) -> None:
        served_from_cache = Usage(cache_read_tokens=1_000_000)
        assert estimate_cost(served_from_cache, "claude-sonnet-4-6") == pytest.approx(0.30)
        # The same tokens at full price (caching off) cost 10x more.
        assert estimate_uncached_cost(served_from_cache, "claude-sonnet-4-6") == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Fact consolidation
# ---------------------------------------------------------------------------


class TestConsolidateFacts:
    def test_no_fact_store_is_noop(self) -> None:
        client, mock = _client()
        assert client.consolidate_facts() == (0, 0)
        mock.messages.parse.assert_not_called()

    def test_fewer_than_two_facts_skips_the_api(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(["only one"]), session_id="s1")
        assert client.consolidate_facts() == (1, 1)
        mock.messages.parse.assert_not_called()

    def test_consolidates_and_replaces(self) -> None:
        store = FakeFactStore(["Loves oak honey", "Favourite honey is oak", "Has a cat"])
        client, mock = _client(fact_store=store, session_id="s1")
        mock.messages.parse.return_value = SimpleNamespace(
            parsed_output=SimpleNamespace(facts=["Loves oak honey", "Has a cat"]),
            usage=_usage(inp=80, out=20),
        )

        assert client.consolidate_facts() == (3, 2)
        assert store.replaced == ["Loves oak honey", "Has a cat"]
        # Spend lands on the session ledger but not last_usage (not a chat turn).
        assert client.session_usage == Usage(input_tokens=80, output_tokens=20)
        assert client.last_usage == Usage()

    def test_strips_blank_entries_from_model_output(self) -> None:
        store = FakeFactStore(["a", "b"])
        client, mock = _client(fact_store=store, session_id="s1")
        mock.messages.parse.return_value = SimpleNamespace(
            parsed_output=SimpleNamespace(facts=["a", "  ", "b "]),
            usage=_usage(),
        )
        client.consolidate_facts()
        assert store.replaced == ["a", "b"]

    def test_wraps_api_error(self) -> None:
        client, mock = _client(fact_store=FakeFactStore(["a", "b"]), session_id="s1")
        mock.messages.parse.side_effect = RuntimeError("boom")
        with pytest.raises(StrohsackAPIError, match="consolidation failed"):
            client.consolidate_facts()

    def test_empty_result_does_not_wipe_the_store(self) -> None:
        """A model that returns no facts (refusal/malformed payload) must never
        erase a non-empty store: consolidate is a no-op and replace_facts is not
        called."""
        store = FakeFactStore(["Loves oak honey", "Has a cat"])
        client, mock = _client(fact_store=store, session_id="s1")
        mock.messages.parse.return_value = SimpleNamespace(
            parsed_output=SimpleNamespace(facts=[]),
            usage=_usage(),
        )
        assert client.consolidate_facts() == (2, 2)  # reported as already-tidy
        assert not hasattr(store, "replaced")  # the destructive call never ran
        assert store.load_facts() == ["Loves oak honey", "Has a cat"]

    def test_all_blank_result_does_not_wipe_the_store(self) -> None:
        """Same guard when the model returns only whitespace entries (which strip
        away to an empty list)."""
        store = FakeFactStore(["a", "b"])
        client, mock = _client(fact_store=store, session_id="s1")
        mock.messages.parse.return_value = SimpleNamespace(
            parsed_output=SimpleNamespace(facts=["  ", ""]),
            usage=_usage(),
        )
        assert client.consolidate_facts() == (2, 2)
        assert not hasattr(store, "replaced")
