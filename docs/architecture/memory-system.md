# Memory System — Strohsack AI

**Version:** 1.0
**Last Updated:** June 20, 2026
**Status:** Reflects Milestone 2 as built — 2A (episodic), 2B→2C (durable facts),
prompt caching, fact consolidation, and the memory-management UI.

---

## Overview

This document is a deep dive on **how Strohsack remembers** — the one subsystem
complex enough to deserve its own write-up. For where it sits in the wider
system (interfaces, conversation manager, eval harness), see
[System Design](system-design.md); for the roadmap and rationale-with-dates, see
the [Project Plan](../../STROHSACK_PROJECT_PLAN.md). Here we cover *only* memory:
its two layers, the read/write architecture that makes recall free, how facts are
cached, consolidated, and managed, and the data model underneath.

Strohsack has **two kinds of memory**, deliberately kept separate because they
behave differently:

| Layer | Holds | Lifetime | Read by | Written by |
|-------|-------|----------|---------|------------|
| **Episodic** (2A) | Full conversation turns | Per session, survives restart | `ConversationManager` | every turn |
| **Durable facts** (2B/2C) | Curated things about the user | Cross-session, long-lived | `StrohsackClient` (injected each turn) | `remember()` tool, on demand |

Both live in **one local SQLite file** (`data/strohsack.db`, gitignored), reached
through two narrow protocols so each consumer depends only on what it needs.

## The load-bearing decision: inject-on-read, tool-on-write

Durable facts are **injected** into the system prompt on read and **written**
through a small custom `remember()` tool. This is the single most important
choice in the memory system, and it was made *against* an earlier working
implementation.

**What it replaced.** Milestone 2B built durable memory on Anthropic's builtin
`memory_20250818` tool, which the model drives by calling `view /memories`
itself. A latency benchmark (`scripts/bench_memory.py`) showed the cost:

- the builtin tool forces a memory read on **every** turn — 2 API round-trips
  even with empty memory;
- on populated reads it ran **~23–34s**;
- the read is **server-driven**, so a system-prompt "don't re-read" nudge had
  **zero** effect — it isn't promptable away.

**Why injection wins.** Reading the facts ourselves and placing them in the
system prompt makes recall a **0-round-trip** operation that *cannot
false-negative* — "Do you remember my name?" costs exactly what "hello" costs,
and Strohsack can never blank on something he's saved. Writes go through a
*custom* tool (not the builtin one), so saving adds a round-trip **only on turns
where Strohsack actually decides to save something**. The model is a far better
judge of "worth keeping" than any keyword cue, so the curation policy lives in
the `remember()` tool's description rather than in brittle trigger detection.

**Round-trip cost, by turn type:**

| Turn | inject-on-read / tool-on-write | builtin `memory_20250818` |
|------|-------------------------------|---------------------------|
| normal chat | 1 call | 2 |
| references the past | 1 call *and always correct* | 3 |
| reveals a new fact | 2 calls | 4 |

A rejected alternative — gating reads behind user cues like "do you remember" —
was set aside (June 2026): keyword matching false-negatives the core feature,
detecting an implicit "he-should-know" tone needs its own classifier call, and
it leaves writes unaddressed. Injection makes reads *free* rather than *rare*:
strictly better on both cost and correctness.

## How a turn uses memory

```
 user message
     │
     ▼
 ConversationManager.send()                      ── appends user turn to history
     │   (also persists turn to episodic store)
     ▼
 StrohsackClient.respond() / stream_response()
     │
     ├─ load_facts()  ───────────────►  SQLiteMemoryStore   (durable facts)
     │      facts injected into the system prompt  (READ — 0 extra round-trips)
     │
     ├─ system = [ persona block | facts block ]   (caching breakpoint between)
     │
     ▼
 Claude API (tool runner loop)
     │
     ├─ no remember() call  ─────────►  1 call, reply returned
     └─ remember(note)      ─────────►  add_fact() → store   (WRITE)
            loop continues to the reply (2 calls total)
     │
     ▼
 reply (or token stream)
     │
     ▼
 ConversationManager records assistant turn  ──►  append_messages()  (episodic)
```

Two subtleties worth calling out:

- **Reply text is gathered across *every* round of the tool loop.** Strohsack
  often replies *and* calls `remember()` in the same turn — his words land in the
  tool-use message and the final post-tool message may carry no text — so
  `respond()` concatenates text from all rounds rather than taking only the last.
- **The plain path still exists.** When no fact store is supplied, the client
  makes a single `messages.create` / `messages.stream` call with no tool and no
  injection. This is the path the personality eval and most tests use, and the
  one that set the Milestone 1B baseline.

## Prompt caching

The system prompt is sent as **content blocks**, split at a `cache_control`
breakpoint:

```
system = [
   { persona prompt ..., "cache_control": {"type": "ephemeral"} },   # stable, cached
   { durable facts ... },                                            # volatile, after the breakpoint
]
```

The persona prompt is byte-identical on every turn and every session, so it
carries the breakpoint and is served from cache (GA prompt caching, no beta
header) at ~0.1× input cost within the 5-minute TTL. Durable facts go in a
**separate block after** the breakpoint, so **saving a fact doesn't invalidate
the cached persona prefix**. Tools render before `system`, so the `remember()`
schema is part of the cached prefix too.

**Verified live:** the ~2.3K-token persona prefix writes to cache on the first
call (`cache_creation`) and reads back on subsequent calls (`cache_read ≈ 2288`),
comfortably above Sonnet 4.6's 2048-token cache minimum. This is a **secondary
cost lever** — it trims *input* cost (most valuable for the rapid-fire eval and
web turns) but does **not** reduce round-trips or latency. The CLI `stats` /
`--stats` readout surfaces `cache_read` / `cache_write` so a silent cache
regression (a `cache_read` stuck at 0 across turns) is visible.

## Fact consolidation (`tidy`)

Facts accumulate messily: near-duplicates, superseded notes, verbose phrasing.
The CLI `tidy` (alias `consolidate`) command has the model **rewrite the whole
list** — merge duplicates, drop stale/superseded notes, tighten each to one
short standalone sentence — using structured output for a reliable list back.

`consolidate_facts()` is conservative by design:

- a **no-op** when there's no fact store or fewer than 2 facts (nothing to merge);
- it **never wipes a non-empty store on an empty result** — an empty list means
  the model refused, lost content, or returned a malformed payload, so it's
  treated as a no-op rather than silently erasing everything;
- the cleaned set is written via `replace_facts`, which stores facts with
  `session_id = NULL` — **promoting them to long-term memory** that per-session
  `forget` no longer touches (only a full wipe does).

This is a **quality** win independent of token pressure: cleaner,
non-contradictory facts mean sharper recall and a smaller injected block.
Verified live (6 messy facts → 4 clean).

## Memory-management UI

A browser-based inspector/editor over the persisted store, reachable as the
**🧠 Memory** page in the Streamlit app (`interfaces/memory_ui.py`, routed
alongside Chat via `st.navigation` in `interfaces/web.py`). It reads and writes
the **same SQLite database the CLI uses** — so you can chat in the terminal and
then view, prune, or wipe what Strohsack kept, from the browser.

Three sections:

- **🍯 Long-term notes** — lists durable facts; delete one (removes *every* copy
  so it leaves the injected prompt entirely) or, behind a confirmation checkbox,
  wipe them all.
- **💬 Conversation history** — a picker over past sessions; selecting one loads
  **only that conversation's** messages (so a rerun reads a single session's
  history, not every session's), and it can be deleted.
- **🧹 Start completely fresh** — a guarded full wipe: every fact and every
  conversation.

The page is backed by two store methods added for it: `list_facts()` (distinct
facts with a stable `id` for widget keys) and `delete_fact(text)` (delete every
copy of a fact by its text). It uses a **cached** `SQLiteMemoryStore` shared
across Streamlit reruns and pages. The web **chat** is wired to the same store as
the CLI — each browser load opens a fresh episodic thread and durable facts are
injected/saved via `remember()` — so the Memory page now inspects sessions and
notes from both the CLI and the web chat. (A fresh thread per load is the
single-user choice for now; per-guest scoping is a later milestone.)

## Data model

One SQLite file, four tables:

```sql
schema_version (version)                       -- single row; drives migrations

sessions  (id PK, created_at, updated_at, label)

messages  (id PK, session_id FK→sessions ON DELETE CASCADE,
           role, content, created_at)          -- episodic history

facts     (id PK, fact,
           session_id FK→sessions ON DELETE SET NULL,
           created_at)                          -- durable facts
```

Design notes:

- **`messages.session_id` cascades** — deleting a session removes its turns.
- **`facts.session_id` is `SET NULL`, not cascade** — a fact *outlives* the
  session it was learned in. `session_id` is **provenance** (and the unit the CLI
  `forget` clears); consolidated/promoted facts carry `NULL`.
- **Fact de-dup is per session, not global.** The same note isn't stored twice
  for one session, but two sessions may each keep their own copy — so `forget`
  stays precise (clearing one session's facts can't delete a fact another session
  still relies on). `load_facts()` / `list_facts()` collapse cross-session
  duplicates for the prompt and the UI.

**Concurrency & robustness.** `SQLiteMemoryStore` is thread-safe — a lock
serializes a single shared connection (`check_same_thread=False`), because the
Streamlit UI reuses one store across reruns. The store is **schema-versioned**: a
`schema_version` row plus an in-place upgrade on open (`_apply_schema` /
`_run_migrations`). Additive changes (e.g. v1→v2 added the `facts` table) ride on
`CREATE TABLE IF NOT EXISTS`; any future non-additive step (ALTER / backfill)
must register in `_run_migrations` before the version stamp advances. The default
DB path is anchored to the **project root** (not the working directory), so the
CLI uses one memory file no matter where it's launched (overridable with
`STROHSACK_DB_PATH`).

## Lifecycle operations

| Action | Surface | Episodic | Durable facts |
|--------|---------|----------|---------------|
| `forget` | CLI | clears **this session's** messages (`clear_session`) | clears **this session's** facts (`clear_facts(session_id)`) — promoted (`NULL`) facts survive |
| `tidy` / `consolidate` | CLI | — | rewrites the list, promotes to `NULL` (`replace_facts`) |
| delete a fact | Web UI | — | removes every copy of one fact (`delete_fact`) |
| delete a conversation | Web UI | deletes a session + its messages (`delete_session`) | — (facts `SET NULL`, survive) |
| full wipe | Web UI | deletes **all** sessions | deletes **all** facts (`clear_facts(None)`) |

## Privacy

The fact store holds real personal details Strohsack learns — names, family,
preferences — so it is **private by construction**:

- the database lives in gitignored `data/` and is **never committed or
  published**;
- the pre-publish scan gate (`scripts/check_no_private_data.py`) operates on
  git-tracked files only, so the DB can't enter the public snapshot;
- family/personal data stays in private config from the start (see Project Plan,
  Pre-Public Hardening).

## Testing

`tests/test_memory.py` covers the store with stubs and no live API: episodic
round-trips and ordering, durable-fact CRUD, per-session de-dup, `list_facts` /
`delete_fact`, consolidation/`replace_facts` semantics (promotion to `NULL`,
survival across `forget`), and schema versioning incl. the v1→v2 migration.
`tests/test_api_client.py` covers both client paths — plain and memory — fact
injection, the `remember()` tool, multi-round text gathering, and the
cache-control system-block assembly. The memory-management UI follows the repo's
existing "no Streamlit UI tests" stance; its logic is exercised at the store
level, with manual `AppTest` smoke-checks during development. The latency
benchmark (`scripts/bench_memory.py`) is intentionally **outside** the suite — it
hits the live API and costs money.

## What's next (not yet built)

- **Episodic rolling summarization** — compressing old *turns* into a running
  summary to bound context as sessions grow. **Deferred on purpose**: with a 1M
  context window, short sessions, and a cached prefix, it only pays off under
  token pressure we don't have. The `--stats` readout is the trigger — build it
  when real sessions show input tokens climbing, not before. (Build-vs-buy when
  we do: Anthropic's server-side compaction beta vs. hand-rolled.)
- **Per-guest memory scoping** (Milestone 3) — partitioning both layers by guest
  once access control lands.

---

*"I learned it in my dreams, of course!" — Strohsack*
