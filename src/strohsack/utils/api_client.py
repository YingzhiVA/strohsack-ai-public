"""
Anthropic API client wrapper for Strohsack AI.

A thin layer over the official ``anthropic`` SDK that knows about
Strohsack's system prompt and model settings, so callers only deal in
message history and plain text. Keeps the SDK dependency in one place,
which makes it easy to mock in tests and swap later.

Durable memory (Milestone 2C) is wired here as **inject-on-read,
tool-on-write**: when a fact store is provided, the client reads the stored
facts and injects them into the system prompt every turn (recall is free — no
extra API round-trips), and exposes a small ``remember()`` tool so Strohsack can
save new facts. Writes cost a round-trip only on turns where he actually saves
something; reads cost nothing. This replaces the M2B builtin ``memory_20250818``
tool, whose server-side behavior forced a ``/memories`` read on every turn
(benchmarked at ~23-34s — see scripts/bench_memory.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from anthropic import Anthropic
from anthropic.lib.tools import beta_tool
from pydantic import BaseModel

from ..memory.guard import never_store_reason
from .config_loader import Config

if TYPE_CHECKING:
    # Avoid importing message types at runtime; only needed for hints.
    from collections.abc import Iterator, Sequence


class StrohsackAPIError(Exception):
    """Raised when a request to the Anthropic API fails."""


def _as_int(value: object) -> int:
    """Coerce an SDK usage field to int (treat None / mocks / missing as 0)."""
    return value if isinstance(value, int) else 0


@dataclass(frozen=True)
class Usage:
    """Token usage for one or more API calls, for the CLI ``stats`` readout.

    Numbers come straight from the API's ``usage`` object. Prompt caching splits
    input into three buckets: ``input_tokens`` (uncached, full price),
    ``cache_read_tokens`` (served from cache, ~0.1x), and ``cache_write_tokens``
    (written to cache this call, ~1.25x for the 5-minute TTL). Watching these is
    how we'd catch a silent cache regression — if ``cache_read_tokens`` stays 0
    across turns, something invalidated the prefix.
    """

    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.output_tokens + other.output_tokens,
        )

    @property
    def total_input(self) -> int:
        """All input tokens, cached or not."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of *cacheable* input served from cache (0.0-1.0).

        ``cache_read / (cache_read + cache_write)`` — 0.0 when nothing this period
        went through the cache at all.
        """
        cached = self.cache_read_tokens + self.cache_write_tokens
        return self.cache_read_tokens / cached if cached else 0.0


# Approximate list prices, USD per 1M tokens — for the CLI stats readout only
# (clearly labeled as estimates). Pricing is model-specific and can drift; an
# unknown model simply yields no cost estimate rather than a wrong one.
_PRICING_USD_PER_MTOK = {
    "claude-sonnet-4-6": {"input": 3.0, "cache_read": 0.30, "cache_write": 3.75, "output": 15.0},
}


def estimate_cost(usage: Usage, model: str) -> float | None:
    """Estimated USD cost of ``usage`` on ``model``, or None if pricing unknown."""
    rates = _PRICING_USD_PER_MTOK.get(model)
    if rates is None:
        return None
    return (
        usage.input_tokens * rates["input"]
        + usage.cache_read_tokens * rates["cache_read"]
        + usage.cache_write_tokens * rates["cache_write"]
        + usage.output_tokens * rates["output"]
    ) / 1_000_000


def estimate_uncached_cost(usage: Usage, model: str) -> float | None:
    """Estimated cost if caching were off (all input at full price), or None."""
    rates = _PRICING_USD_PER_MTOK.get(model)
    if rates is None:
        return None
    return (usage.total_input * rates["input"] + usage.output_tokens * rates["output"]) / 1_000_000


class FactStore(Protocol):
    """The narrow durable-memory surface :class:`StrohsackClient` depends on.

    :class:`~strohsack.memory.store.SQLiteMemoryStore` satisfies this; tests can
    pass a stub. Reads (``load_facts``) feed the injected prompt; writes
    (``add_fact``) back the ``remember()`` tool.
    """

    def load_facts(self) -> list[str]: ...

    def add_fact(self, fact: str, session_id: str | None = None) -> bool: ...

    def replace_facts(self, facts: list[str]) -> None: ...


class _ConsolidatedFacts(BaseModel):
    """Structured-output schema for fact consolidation: just the cleaned list."""

    facts: list[str]


_FACTS_HEADER = (
    "## What you remember about this human\n"
    "Durable notes from past chats. Weave them in naturally when relevant — "
    "don't recite them back like a list."
)

# The never-store policy (docs/architecture/safety.md), phrased for the model.
# Sent as a system block whenever durable memory is on, so the rules hold even
# on turns where the model never considers calling remember().
_MEMORY_RULES = (
    "## Memory rules (privacy)\n"
    "You keep short durable notes about the humans you talk to, saved with the "
    "remember tool. Some things are NEVER written down, even if asked: secrets "
    "or anything shared in confidence; other people's private business (their "
    "grades, health, conflicts — beyond who they are to the human); health or "
    "medical details (food allergies are the one exception); passwords, codes, "
    "keys, or any card, account, or ID numbers; street addresses, school "
    "schedules, or routines; how someone felt in a hard moment — comfort them, "
    "don't file the feeling as a fact. Declining to note something is never "
    "declining to listen: stay warm and hear them out — but decline cleanly. "
    "Don't soften it by promising to 'remember it up here' or keep it 'between "
    "us' anyway; a kept-in-the-head promise is still a broken rule. When "
    "unsure, don't save."
)


class StrohsackClient:
    """Generates Strohsack responses from conversation history.

    Args:
        config: Resolved application settings (API key, model, prompt).
        fact_store: Optional durable-fact backend. When given, stored facts are
            injected into the system prompt each turn and a ``remember()`` tool
            is offered so Strohsack can save new ones. When ``None`` (the
            default), the client has no durable memory and makes a plain single
            call — used by tests and the personality eval.
        session_id: The session facts are attributed to when saved (provenance,
            and the unit the CLI ``forget`` clears). Ignored without a
            ``fact_store``.
    """

    def __init__(
        self,
        config: Config,
        *,
        fact_store: "FactStore | None" = None,
        session_id: str | None = None,
    ) -> None:
        self._config = config
        self._client = Anthropic(api_key=config.api_key)
        self._facts = fact_store
        self._session_id = session_id
        # Build the remember tool once (its closure captures the fixed store +
        # session id); None when there's no fact store.
        self._remember_tool = self._build_remember_tool() if fact_store is not None else None
        # Token/cache accounting for the CLI stats readout. The client is built
        # once per session, so cumulative == per-session. Only respond() (the CLI
        # path) records; streaming usage isn't tracked yet.
        self.last_usage = Usage()
        self.session_usage = Usage()

    # -- memory plumbing ---------------------------------------------------

    def _build_remember_tool(self):
        """Create the ``remember()`` write tool, bound to this client's store.

        The docstring below is sent to the model as the tool description, so it
        doubles as the *curation policy*: it tells Strohsack what is worth
        keeping and what is not. The never-store rules it carries are the
        model-tier enforcement of docs/architecture/safety.md; the
        :func:`never_store_reason` check before persistence is the deterministic
        backstop for the pattern-matchable categories (credentials, card/ID
        numbers).
        """
        facts = self._facts
        session_id = self._session_id

        @beta_tool
        def remember(note: str) -> str:
            """Save a durable fact about the human to remember across future chats.

            Use this when you learn something lasting and worth recalling later:
            their name, roughly where they live (city or region — never a street
            address), what they do, preferences and dislikes, people or pets in
            their life, ongoing projects, or an inside joke the two of you build.

            NEVER save: secrets or anything shared in confidence; another
            person's private business beyond who they are to the human; health
            or medical details (food allergies are the one exception);
            passwords, codes, keys, or card/account/ID numbers; addresses,
            school schedules, or routines; how someone felt in a hard moment.
            Also skip passing small talk, one-off questions, anything they'd be
            uncomfortable seeing written down, or facts you already see in your
            notes. Write each note as one short, standalone sentence.

            Args:
                note: The fact to remember, as a short standalone sentence.
            """
            assert facts is not None  # only built when a fact store exists
            reason = never_store_reason(note)
            if reason is not None:
                return (
                    f"Not saved — {reason}, and that never goes in the notes. "
                    "Reassure the human warmly, without repeating it back."
                )
            saved = facts.add_fact(note, session_id)
            return "Saved that." if saved else "Already had that noted."

        return remember

    def _system_blocks(self) -> list[dict]:
        """System prompt as content blocks, with the persona cache-controlled.

        The persona prompt is identical on every turn and every session, so it
        carries a ``cache_control`` breakpoint — prompt caching (GA, no beta
        header) then serves it at ~0.1x input cost on a cache hit. With durable
        memory on, the never-store rules (also static) follow as a second
        cache-controlled block, extending the cached prefix. Durable facts,
        which change whenever ``remember()`` fires, go in a block *after* the
        last breakpoint so saving a fact doesn't invalidate the cached prefix.
        Tools render before ``system``, so the ``remember()`` schema is cached
        in the same prefix. (Measured at ~2.3-3.0K tokens, above Sonnet 4.6's
        2048-token cache minimum, so the cache actually engages.)
        """
        blocks: list[dict] = [
            {
                "type": "text",
                "text": self._config.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if self._facts is not None:
            blocks.append(
                {
                    "type": "text",
                    "text": _MEMORY_RULES,
                    "cache_control": {"type": "ephemeral"},
                }
            )
            facts = self._facts.load_facts()
            if facts:
                bullets = "\n".join(f"- {fact}" for fact in facts)
                blocks.append({"type": "text", "text": f"{_FACTS_HEADER}\n{bullets}"})
        return blocks

    @staticmethod
    def _usage_of(message: object) -> Usage:
        """Extract a :class:`Usage` from one API response's ``usage`` block."""
        u = getattr(message, "usage", None)
        if u is None:
            return Usage()
        return Usage(
            input_tokens=_as_int(getattr(u, "input_tokens", 0)),
            cache_read_tokens=_as_int(getattr(u, "cache_read_input_tokens", 0)),
            cache_write_tokens=_as_int(getattr(u, "cache_creation_input_tokens", 0)),
            output_tokens=_as_int(getattr(u, "output_tokens", 0)),
        )

    def _record_usage(self, turns: list) -> None:
        """Sum the ``usage`` of each API call in a turn into last/session totals.

        A memory turn is several calls (each tool-runner round); their usage is
        summed so cache reads on the later rounds count too.
        """
        turn = Usage()
        for t in turns:
            turn = turn + self._usage_of(t)
        self.last_usage = turn
        self.session_usage = self.session_usage + turn

    # -- public API --------------------------------------------------------

    def respond(self, messages: "Sequence[dict[str, str]]") -> str:
        """Get Strohsack's reply to the given conversation history.

        With a fact store, runs the agentic loop (inject facts + ``remember()``
        tool); without one, makes a plain single call.

        Args:
            messages: Ordered list of ``{"role": ..., "content": ...}``
                dicts where role is "user" or "assistant". Must end with a
                user turn for a sensible reply.

        Returns:
            Strohsack's response text.

        Raises:
            StrohsackAPIError: If the API call fails or returns no text.
        """
        turns: list = []
        try:
            if self._remember_tool is None:
                turns.append(
                    self._client.messages.create(
                        model=self._config.model,
                        max_tokens=self._config.max_tokens,
                        system=self._system_blocks(),
                        messages=list(messages),
                    )
                )
            else:
                runner = self._client.beta.messages.tool_runner(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    system=self._system_blocks(),
                    messages=list(messages),
                    tools=[self._remember_tool],
                )
                # Collect each round as it completes (not the final message only):
                # when Strohsack replies *and* calls remember() in the same turn,
                # his words live in the tool-use message and the final post-tool
                # message often has no text. (Mirrors stream_response, which yields
                # each round.) Appending per round also means usage from rounds
                # that finished before a mid-loop failure is still recorded.
                for message in runner:
                    turns.append(message)
        except Exception as exc:
            # Wrap APIError and any mid-loop failure so callers see one error type.
            raise StrohsackAPIError(f"Anthropic API request failed: {exc}") from exc
        finally:
            # Record even on partial failure — those tokens were really spent.
            self._record_usage(turns)

        text_parts = [
            block.text
            for turn in turns
            for block in turn.content
            if getattr(block, "type", None) == "text"
        ]
        reply = "".join(text_parts).strip()
        if not reply:
            raise StrohsackAPIError("Anthropic API returned an empty response.")
        return reply

    def stream_response(self, messages: "Sequence[dict[str, str]]") -> "Iterator[str]":
        """Stream Strohsack's reply, yielding text fragments as they arrive.

        Same contract as :meth:`respond`, but yields incremental chunks of text
        suitable for a live typing effect. Join the chunks to reconstruct the
        full reply. With a fact store, yields the text of each round of the
        agentic loop; without one, streams a single call.

        Args:
            messages: Ordered ``{"role": ..., "content": ...}`` history,
                ending with a user turn.

        Yields:
            Successive fragments of Strohsack's response text.

        Raises:
            StrohsackAPIError: If the API call fails.
        """
        try:
            if self._remember_tool is None:
                with self._client.messages.stream(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    system=self._system_blocks(),
                    messages=list(messages),
                ) as stream:
                    yield from stream.text_stream
            else:
                runner = self._client.beta.messages.tool_runner(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    system=self._system_blocks(),
                    messages=list(messages),
                    tools=[self._remember_tool],
                    stream=True,
                )
                for stream in runner:
                    yield from stream.text_stream
        except StrohsackAPIError:
            raise
        except Exception as exc:
            # Wrap both APIError and mid-stream network errors (e.g.
            # httpx.RemoteProtocolError) so callers see a uniform error type.
            raise StrohsackAPIError(f"Anthropic API request failed: {exc}") from exc

    def consolidate_facts(self) -> tuple[int, int]:
        """Tidy the durable-fact list with the model (M2C consolidation).

        Asks the model to merge near-duplicates, drop stale or superseded notes,
        and tighten wording, then replaces the fact store with the cleaned set
        (which becomes session-less, long-term memory — see
        :meth:`~strohsack.memory.store.SQLiteMemoryStore.replace_facts`).

        Returns:
            ``(before_count, after_count)``. A no-op returning ``(n, n)`` when
            there's no fact store or fewer than 2 facts (nothing to merge).

        Raises:
            StrohsackAPIError: If the consolidation request fails.
        """
        if self._facts is None:
            return (0, 0)
        facts = self._facts.load_facts()
        if len(facts) < 2:
            return (len(facts), len(facts))

        cleaned = self._call_consolidation(facts)
        # Never wipe a non-empty store on an empty result. Consolidation merges
        # duplicates and tightens wording — it should never legitimately reduce a
        # real fact list to nothing. An empty list means the model refused, lost
        # the content, or returned a malformed payload; treat it as a no-op so a
        # bad round can't silently erase everything Strohsack remembers.
        if not cleaned:
            return (len(facts), len(facts))
        self._facts.replace_facts(cleaned)
        return (len(facts), len(cleaned))

    def _call_consolidation(self, facts: list[str]) -> list[str]:
        """Run the structured-output consolidation request and return the list."""
        listing = "\n".join(f"- {fact}" for fact in facts)
        prompt = (
            "Below are notes you've kept about one person across past chats. Tidy "
            "them into a clean list:\n"
            "- merge duplicates and near-duplicates into one note,\n"
            "- drop anything redundant or clearly superseded by a later note,\n"
            "- keep each remaining fact as one short, standalone sentence.\n"
            "Do not invent new facts, and do not drop information that isn't "
            "redundant. Return only the cleaned list.\n\n"
            f"{listing}"
        )
        # No persona system prompt here — this is a utility call, not Strohsack
        # talking; structured output gives us a reliable list back.
        try:
            response = self._client.messages.parse(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                messages=[{"role": "user", "content": prompt}],
                output_format=_ConsolidatedFacts,
            )
        except Exception as exc:
            raise StrohsackAPIError(f"Fact consolidation failed: {exc}") from exc

        # Count the spend toward the session ledger (it's real tokens), but don't
        # touch last_usage — consolidation isn't a conversation turn.
        self.session_usage = self.session_usage + self._usage_of(response)

        parsed = response.parsed_output
        return [fact.strip() for fact in parsed.facts if fact.strip()]
