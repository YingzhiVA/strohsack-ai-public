# System Design — Strohsack AI

**Version:** 2.1
**Last Updated:** June 20, 2026
**Status:** Reflects Milestone 1 (1A/1B/1C) and Milestone 2 memory (2A episodic, 2B/2C durable facts, caching, consolidation, memory UI)

> For a deep dive on the memory subsystem specifically — the two layers,
> inject-on-read/tool-on-write, caching, consolidation, and the management UI —
> see [Memory System](memory-system.md).

---

## Overview

Strohsack AI is a personality-driven conversational agent: a lazy, honey-obsessed
bear backed by the Claude API. This document describes the system **as it is built
today**, then sketches where the planned milestones will plug in. For the roadmap
and milestone deliverables, see the [Project Plan](../../STROHSACK_PROJECT_PLAN.md);
this document is about *how the pieces fit together*, not *what's coming when*.

The guiding principle so far has been **a thin, well-seamed core**: the model API,
the conversation state, the personality text, and the user-facing surface are each
isolated behind a small interface, so any one can be swapped or mocked without
touching the others. That seam discipline is what makes the eval harness possible
(it drives the same `Responder` the UIs use, with a stub instead of the network)
and is what the memory and access-control milestones will hook into.

## Current Architecture

```
┌──────────────────────────────┐     ┌──────────────────────────────┐
│   CLI  (interfaces/cli.py)   │     │   Web  (interfaces/web.py)   │
│  read-reply-print loop       │     │  Streamlit, streaming reply  │
└───────────────┬──────────────┘     └───────────────┬──────────────┘
                │   greeting()/farewell()  (interfaces/__init__.py)
                └───────────────┬───────────────────┘
                                │  send() / send_stream()
                ┌───────────────┴──────────────────┐
                │       ConversationManager         │
                │   (conversation/manager.py)       │
                │  - holds one session's history    │
                │  - appends user turn, gets reply  │
                │  - rolls back history on failure  │
                └───────────────┬──────────────────┘
                                │  Responder / StreamingResponder protocol
                ┌───────────────┴──────────────────┐
                │         StrohsackClient           │
                │      (utils/api_client.py)        │
                │  - respond() / stream_response()  │
                │  - wraps the anthropic SDK        │
                │  - injects durable facts (read)   │
                │  - offers remember() tool (write) │
                └───────┬───────────────────┬───────┘
                        │                   │ load_facts() / add_fact()
                        │            ┌───────┴───────────────────┐
                        │            │     SQLiteMemoryStore      │
                        │            │      (memory/store.py)     │
                        │            │  episodic: sessions+msgs   │
                        │            │  durable:  facts table     │
                        │            │  schema_version + migrate  │
                        │            └───────┬───────────────────┘
                        │                    │  data/strohsack.db (gitignored)
                ┌───────┴────────┐         ┌─┴───────────────────────┐
                │   Claude API   │         │  Config (config_loader) │
                │  (Anthropic)   │◄────────│  api key, model, tokens │
                └────────────────┘         │  system prompt from .txt │
                                           └─────────────────────────┘

The SQLiteMemoryStore backs both layers: ConversationManager reads/writes
episodic history through it (MemoryStore protocol), and StrohsackClient
reads/writes durable facts through it (FactStore protocol).

Eval harness (eval/) drives the same Responder seam with a stubbed or live
client, scoring replies with an LLM-as-judge against the trait rubric.
```

### Component responsibilities

#### Interfaces — `strohsack/interfaces/`
The user-facing surfaces. Both are deliberately thin: they own only
input/output and session lifecycle, and delegate every turn to a
`ConversationManager`.

- **CLI** (`cli.py`) — a synchronous read-reply-print loop. `python -m
  strohsack.interfaces.cli`. Commands: `exit`/`quit`/`bye`; `forget` (wipe this
  chat + its facts); `tidy`/`consolidate` (have the model merge near-duplicate /
  drop stale durable facts); `stats` (session token/cache readout); plus
  Ctrl-C/Ctrl-D. API errors surface as an in-character "Strohsack is napping"
  notice without crashing. `--stats` adds a per-turn token/cache line — a cheap
  guard that prompt caching is still landing (a `cache_read` of 0 across turns
  means a silent cache invalidation).
- **Web** (`web.py`) — a Streamlit app with **token streaming** for a live
  typing effect. Streamlit re-runs the whole script on every interaction, so
  the conversation (and the memory-wired client behind it) live in
  `st.session_state` to survive reruns; immutable config is cached via
  `@st.cache_resource`, and the per-session client/manager are built once per
  browser session from it. It mirrors the CLI's memory wiring (`fact_store` +
  `session_id` on the client, `store` + `session_id` on the manager): each
  browser load opens a **fresh episodic thread** (single-user for now;
  per-guest scoping is a later milestone) while **durable facts** carry across
  threads, injected each turn and saved via `remember()`. "New nap" opens
  another fresh thread. Two pages (`st.navigation`): **Chat**, and a **🧠
  Memory** page (`memory_ui.py`) — a view/edit/wipe inspector over the same
  persisted store; see [Memory System](memory-system.md#memory-management-ui).
- **Greetings/farewells** (`__init__.py`) — shared pools of in-character opener
  and closer lines, picked at random so both surfaces speak with one voice and
  Strohsack doesn't say the same thing every session. These are *not* part of
  the model history; they're presentation only.

#### Conversation Manager — `strohsack/conversation/manager.py`
Owns the message history for **one session** and orchestrates each turn. It
appends the user turn, asks the responder for a reply, and records the reply.
Two key correctness properties:

- **History stays valid on failure.** If the responder raises mid-turn, the
  user turn is rolled back, so the next attempt starts from clean state. The
  streaming path catches `BaseException` (not just `Exception`) so Streamlit's
  `RerunException` and `GeneratorExit` can't leave an orphaned user turn.
- **It depends on protocols, not concretes.** `Responder` (and
  `StreamingResponder`) are `typing.Protocol`s. Anything satisfying them works —
  the real client in production, a stub in tests. An optional `MemoryStore` +
  `session_id` can be passed to persist history across restarts (Milestone 2A);
  when omitted, history lives only for the lifetime of the object.

#### API Client — `strohsack/utils/api_client.py`
The single place that touches the `anthropic` SDK. `StrohsackClient` turns a
message history into either a full reply (`respond`) or a stream of text
fragments (`stream_response`), injecting the model, token budget, and system
prompt from `Config`. All SDK and mid-stream network errors are wrapped in a
single `StrohsackAPIError` so callers see one uniform error type. Concentrating
the dependency here is what keeps it mockable and swappable.

It has **two paths**, chosen by whether a `FactStore` was supplied:

- **No fact store** — a plain single call (`messages.create` / `messages.stream`).
  Used by tests and the personality eval, and it's the path that set the 1B
  baseline.
- **With a fact store (durable memory, 2C)** — before each turn the client
  *injects* the stored facts into the system prompt (recall costs no extra API
  round-trips) and offers a small `remember(note)` tool through the SDK's tool
  runner so Strohsack can save new facts. A save costs one extra round-trip
  *only* on turns where he actually calls the tool. `respond()` gathers reply
  text from **every** round of the tool loop, because Strohsack often replies and
  calls `remember()` in the same turn (his words land in the tool-use message,
  and the final post-tool message may carry no text).

This **inject-on-read / tool-on-write** split is the load-bearing memory
decision; see Design Decisions below for why it replaced the builtin memory tool.

#### Memory store — `strohsack/memory/store.py`
A single SQLite database (`data/strohsack.db`, gitignored) backs **two** memory
layers behind two narrow protocols, so each consumer depends only on what it
needs:

- **Episodic (2A)** — `sessions` + `messages` tables hold full conversation
  history. `ConversationManager` reads/writes this via the `MemoryStore`
  protocol (`load_history` / `append_messages`), so a session survives a restart
  and the CLI can resume the last one.
- **Durable facts (2B/2C)** — a `facts` table holds the lasting things Strohsack
  learns about the user. `StrohsackClient` reads/writes this via the `FactStore`
  protocol (`load_facts` for injection, `add_fact` from the `remember()` tool).
  Facts are cross-session; `session_id` is provenance (and the unit the CLI
  `forget` clears). De-dup is **per session** so `forget` stays precise — clearing
  one session's facts can't delete a fact another session still relies on — and
  `load_facts` collapses any cross-session duplicates for the prompt.
  **Consolidation** (`tidy`/`consolidate`) has the model rewrite the whole list —
  merging near-duplicates, dropping stale notes — and `replace_facts` swaps the
  table for the result with `session_id = NULL`, promoting them to long-term
  memory that per-session `forget` no longer touches (only a full wipe does).

`SQLiteMemoryStore` is thread-safe (a lock serializes a shared connection, since
the Streamlit UI reuses one store across reruns) and **schema-versioned**: a
`schema_version` table plus an in-place migration on open (`_apply_schema` /
`_run_migrations`) upgrades older databases additively. The default DB path is
anchored to the project root, not the working directory, so the CLI uses one
memory file regardless of where it's launched from (overridable with
`STROHSACK_DB_PATH`).

#### Configuration — `strohsack/utils/config_loader.py`
Resolves everything needed to start a conversation into a frozen `Config`
dataclass: API key, model, max tokens (from `.env` / environment), and the
**system prompt text loaded from disk** (`personality/strohsack_system_prompt_v0.1.txt`).
Loading the prompt from a file means personality edits never require code
changes. `load_config(require_api_key=False, use_dotenv=False)` lets tests
exercise prompt assembly without a key or a stray `.env`.

#### Personality — `strohsack/personality/`
Currently just the versioned system prompt text file. There is no code here yet;
the "personality engine" of the original design is, for now, *the prompt plus
the eval harness that holds it accountable*. This is intentional — the cheapest
correct version of a personality engine is a well-tested prompt.

#### Evaluation harness — `strohsack/eval/`
The mechanism that keeps the personality honest across prompt edits (Milestone
1B). It's a small pipeline:

- **`rubric.py`** — defines the scored personality `Trait`s (honey obsession,
  proud laziness, warmth, third-person, knowledge handling, brevity, and the
  **critical** `never_mean`), the in-character threshold, the critical floor,
  and the target-trait weighting. The trait descriptions are written to be
  handed verbatim to the judge.
- **`judge.py`** — `LLMJudge` scores a (probe, reply) pair by calling Claude
  with the rubric as its system prompt and parsing back structured per-trait
  JSON. `Verdict.from_scores` computes a **targets-weighted** overall (traits a
  probe was designed to exercise count more) and flags a `critical_failure` if a
  critical trait falls below the floor — being cruel can't be averaged away by
  six good traits. A `Judge` Protocol lets the runner be tested with a stub.
- **`runner.py`** — loads probes from `probes.yaml`, drives each through the
  `Responder` seam as an independent single-turn conversation, scores it, and
  aggregates into an `EvalReport` (in-character rate, per-trait averages,
  worst-N). Per-probe failures are isolated and reported separately rather than
  aborting the run. `format_report` renders a markdown summary.

The eval harness reuses the **same `Responder` protocol** the UIs use, so it
measures the real production path, and runs fully offline in tests with stubs.

### Data flow — a single turn (current)

1. Interface reads the user's message.
2. Interface calls `ConversationManager.send()` (or `send_stream()`).
3. Manager validates, appends the user turn, and calls the responder.
4. `StrohsackClient` builds the `system` prompt — the Strohsack prompt, plus any
   durable facts loaded from the store (memory path) — and sends it with the full
   message history to the Claude API, with model/token settings from `Config`.
5. On the memory path, the tool runner loops: if Strohsack calls `remember()`,
   the fact is written to the store and the loop continues to his reply;
   otherwise it's a single call. Reply text is gathered across all rounds.
6. Reply (or token stream) comes back; the manager records the assistant turn and
   persists it to the episodic store.
7. Interface renders it. On error, history is rolled back and an in-character
   notice is shown.

## Design Decisions

### Protocol seams over inheritance
`Responder`/`StreamingResponder`/`Judge` are structural `Protocol`s, not base
classes. This gives mockability (tests pass plain stubs) and swappability (a
future local model or different provider only has to satisfy the protocol)
without an inheritance hierarchy. It's the single most load-bearing decision in
the codebase — the eval harness, the tests, and the future memory layer all ride
on these seams.

### Durable memory: inject-on-read, tool-on-write
Strohsack's durable facts are **injected** into the system prompt on read and
written through a custom `remember()` tool — recall is free, only saving costs a
round-trip. This replaced an earlier implementation (2B) built on Anthropic's
builtin `memory_20250818` tool, which the model drives by calling `view
/memories` itself. A latency benchmark (`scripts/bench_memory.py`) showed that
builtin tool forces a memory read on *every* turn — 2 API round-trips even with
empty memory, ~23–34s on populated reads — and the read is server-driven, so a
system-prompt "don't re-read" nudge had zero effect. The fix was architectural,
not promptable: reading the facts ourselves and putting them in context makes
recall a 0-round-trip operation that can't false-negative, while a *custom* write
tool (unlike the builtin one) adds a round-trip only when Strohsack actually
saves something. The model is also a better judge of "worth keeping" than any
keyword cue, so the curation policy lives in the `remember()` tool's description.

### System prompt in a versioned text file, not code
Personality is the product. Keeping the prompt in
`personality/strohsack_system_prompt_v0.1.txt` (versioned in the filename) means
iterating on character is a content edit, reviewable on its own, and the eval
harness can pin behavior across versions.

### Eval harness as a first-class component, early
Personality regressions are silent — a prompt tweak that fixes one thing can
flatten the voice elsewhere. Building the LLM-as-judge harness at Milestone 1B
(before memory, before multi-user) means every later change can be measured
against the trait rubric instead of eyeballed.

### Streaming in the web UI, driven manually
The web UI drives the token stream into a single placeholder (text + a `▌`
cursor) rather than using `st.write_stream`, because the manual approach renders
far more smoothly and shows tokens as they actually arrive. The CLI stays
non-streaming for simplicity.

### Why Claude / Python / Streamlit
Claude for the model (strong instruction-following for personality work, and the
author is building toward the Anthropic ecosystem). Python for the ecosystem and
the author's familiarity. Streamlit for the web UI because it gets a
demo-quality chat surface up in a single file with minimal frontend work —
appropriate for a portfolio project at this stage. FastAPI is the likely
successor when a real backend is needed.

## Testing

`tests/` covers the seams that matter: `test_config_loader.py` (env parsing,
prompt loading, error cases), `test_conversation.py` (history management,
rollback on failure, streaming), `test_eval.py` (rubric scoring, verdict
weighting, report aggregation), `test_api_client.py` (both client paths — plain
and memory — fact injection, the `remember()` tool, multi-round text gathering,
error wrapping), and `test_memory.py` (episodic round-trips, durable-fact CRUD,
per-session de-dup, schema versioning and the v1→v2 migration) — all using stubs,
no live API. The latency benchmark (`scripts/bench_memory.py`) is intentionally
*outside* the suite: it hits the live API and costs money, so it's run by hand.

## Security & Privacy (current state)

- API key is read from `.env` / environment and never committed (`.env.example`
  is the template).
- Conversation history **and durable facts** are persisted in a local SQLite
  database (`data/strohsack.db`, gitignored) — never committed, never published.
  The fact store holds real personal details Strohsack learns (names, family,
  preferences), so it is private by construction. The pre-publish scan gate
  (`scripts/check_no_private_data.py`) operates on git-tracked files only, so the
  database never enters the public snapshot. Family/personal data stays in private
  config from the start (see Project Plan, Pre-Public Hardening).

## What's Planned (not yet built)

These are deliberately **absent** from the diagram above because they don't
exist yet. Where each will attach:

- **Milestone 2 — Memory.** *(Built — see Current Architecture above and the
  [Memory System](memory-system.md) deep dive.)* 2A: episodic persistence via
  `SQLiteMemoryStore`. 2B/2C: durable facts via inject-on-read / tool-on-write
  (no hand-rolled RAG/embeddings — 1M context makes that unnecessary at personal
  scale), prompt caching on the stable prefix, model-driven fact consolidation
  (`tidy`), and the memory-management UI. **The one remaining 2C item** is
  episodic rolling summarization, deferred until `--stats` shows real token
  pressure (1M context + short sessions + cached prefix make it premature today).
- **Milestone 2.5 — Safety & guardrails.** Likely a filter stage around the
  client/responder seam.
- **Milestone 3 — Access control & guest sessions.** A user/guest manager in
  front of the conversation, gating who can talk to Strohsack and scoping memory
  per guest. Folds in the public/private data split.
- **Milestone 4 — Voice.** STT (Whisper) → existing text pipeline → TTS
  (ElevenLabs/Azure), as a new interface alongside CLI and web.
- **Milestone 5 — Physical.** Raspberry Pi host, USB mic, Bluetooth speaker.

Each of these slots into an existing seam rather than reworking the core, which
is the whole point of the current structure.

---

*"I learned it in my dreams, of course!" — Strohsack*
