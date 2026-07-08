# Implementing AI Memory — or: The Feature I Almost Over-Engineered Twice

**Date:** July 2026
**Milestone:** 2 — Memory System (2A episodic, 2B agentic tool, 2C fast memory architecture)
**Status:** Draft

---

## What I Set Out to Build

Strohsack could hold a conversation, but he had the memory of a goldfish: close
the terminal and everything was gone. Milestone 2 was about making him
*remember* — both the conversation you were just having (pick up where you left
off after a restart) and the durable things he learns about you over weeks
("your name is on the tip of my snout... it's the honey, it clogs the
memory").

Those turned out to be two genuinely different problems, and treating them as
one thing is, I now believe, where a lot of memory implementations go wrong.

## Why This Matters

"He remembers me" is the whole emotional product. A chatbot that asks your
name every day is software; a bear who knows you love oak honey and asks how
the school project went is a character. Technically, it's also the milestone
where the project stopped being "a prompt with a loop around it" and grew a
real data layer, a benchmark, and its first architecture decision that
*reversed a working implementation*.

## The Plan I Didn't Follow

The original project plan — written in 2025, like a good 2025 plan — called
for the classic RAG recipe: embed every conversation chunk, store vectors in
ChromaDB or FAISS, retrieve by similarity at question time.

Before writing any of it, I re-examined the assumption, and two things had
changed under the plan's feet:

1. **Context windows got huge.** With a 1M-token context, the *entire
   conversation history of a family's use of a plush bear* fits in context.
   At personal scale, retrieval solves a problem I don't have.
2. **Memory became a first-class tool.** Anthropic ships a `memory_20250818`
   tool where the model curates its own durable facts. No hand-rolled
   embedding pipeline needed.

So the RAG milestone became: SQLite for episodic history (2A), and the
built-in memory tool for durable facts (2B). Lesson one of this milestone:
**re-read your own plan skeptically before implementing it** — a plan is a
snapshot of what was sensible when it was written.

## 2A: Episodic Memory — The Boring Layer That Behaved

Conversation history went into SQLite: a `sessions` table, a `messages`
table, a thread lock, and a gitignored `data/` directory so nothing private
ever reaches the repo. The CLI resumes your last session by default; `--new`
starts fresh; `forget` wipes the current one.

The design decision that paid off was a narrow `MemoryStore` Protocol between
the conversation manager and the database — mirroring the `Responder`
Protocol from Milestone 1. The manager doesn't know SQLite exists; tests pass
a fake; and when I later needed to rip out and replace the *semantic* layer
(spoiler), the episodic layer didn't move.

## 2B: The Built-in Memory Tool — Works, But Benchmark It

Wiring up `memory_20250818` was pleasantly quick, and watching the model
decide on its own to jot down a fact is genuinely delightful. Ship it, right?

Almost. Chat turns *felt* slow, and I've learned to distrust "feels" in both
directions, so I wrote a small latency benchmark before moving on. The
numbers were structural, not noise:

| Turn type | API round-trips | Wall time |
|---|---|---|
| Any turn, even with empty memory | 2 | — |
| Turn that reads memory | 3 | ~23s |
| Turn that reads + writes | 4 | ~34s |

The built-in tool has the model read `/memories` at the start of **every**
turn. The read is server-driven — the SDK sends only the tool's name, so
there's nothing client-side to intercept — and when I A/B-tested a system
prompt nudge ("don't re-read memory you've already seen"), it changed
*nothing*. The round-trip count was identical. The cost could not be
prompted away.

For a real-time chat with a bear, a 23-second "hello" is not a latency
problem, it's a product death sentence.

## 2C: Inject-on-Read, Tool-on-Write

The fix came from noticing that reads and writes want opposite treatments:

- **Reads should be free and constant.** So don't make memory something the
  model *fetches* — make it something the model *already has*. Every turn, the
  client loads the stored facts (now a `facts` table in the same SQLite file)
  and injects them into the system prompt. Zero extra round-trips, and — the
  part I care most about — zero false negatives. There is no turn where
  Strohsack blanks on something he should know because a retrieval heuristic
  didn't fire. "Do you remember me?" costs exactly what "hello" costs.
- **Writes should cost only when they happen.** A tiny custom `remember(note)`
  tool — a plain user-defined tool, *not* the built-in one, so no forced
  pre-read — adds one round-trip only on turns where the model decides
  something is worth keeping. The model turns out to be a much better judge
  of "worth keeping" than any keyword rule I could write.

Turn costs went from 2/3/4 round-trips (normal / recall / learn) to
**1/1/2** — and the "1" for recall is also *always correct*.

I did seriously consider the cheaper-looking alternative: keep the tool-based
read but gate it on user cues like "do you remember...". It falls apart on
contact: keyword matching false-negatives the core feature (people reference
the past implicitly all the time), detecting an implicit "he should know
this" tone needs its own classifier call (there goes the savings), and it
does nothing about writes. Injection makes reads *free* rather than *rare* —
strictly better on both cost and correctness.

## The Supporting Cast

**Prompt caching.** The persona prompt (~2.3K tokens) is identical every
turn, so it carries a `cache_control` breakpoint and gets served from cache
at ~0.1× input price. The injected facts live in a *separate* block after
the breakpoint — so saving a new fact doesn't invalidate the cached persona.
Verified live rather than assumed: the CLI's `--stats` readout shows the
cache reads, and doubles as a tripwire for silently breaking the cache later.

**Fact consolidation.** Facts accumulate as the model wrote them in the
moment, so a `tidy` command has the model rewrite its own notes: merge
near-duplicates, drop superseded ones, tighten wording. One guard here was
non-negotiable — if the model returns an empty list, that's a malfunction,
not a instruction to erase everything the bear knows. An empty consolidation
result is a no-op, never a wipe.

**A memory management UI.** A small Streamlit page lists what Strohsack
knows, lets you delete a fact or a whole conversation, and offers the
full "forget everything" lever. Building it forced clarity about deletion
semantics I'd been vague on (deleting a *conversation* keeps the facts
learned in it — they're promoted to long-term memory; deleting a *fact*
removes every copy).

**The thing I didn't build.** Rolling summarization of old conversation
turns is designed, documented — and deliberately unbuilt. With a 1M context,
short sessions, and a cached prefix, there's no token pressure to relieve
yet. The `--stats` readout is the tripwire: when real sessions show input
tokens climbing, that's the moment. Deferring with a written trigger
condition felt much better than deferring by forgetting.

## Learnings

- **Benchmark before you architect around a dependency.** The built-in memory
  tool "worked" in every functional sense. Only the benchmark revealed a
  structural cost that no amount of prompting could tune away — and that
  finding reshaped the whole milestone.
- **Reads and writes deserve different mechanisms.** Injection for reads,
  a tool for writes. Most of the memory designs I'd read collapse these into
  one retrieval mechanism, and inherit the worst properties of both.
- **Let the model curate, deterministically bounded.** Model judgment for
  "what's worth keeping", hard code for "what must never happen" (empty
  consolidation can't wipe the store; a failed API call rolls the
  conversation history back).
- **Protocols keep refactors small.** Swapping the entire semantic-memory
  backend (2B → 2C) touched the client and nothing else. The Protocol
  boundaries drawn in Milestone 1 are why.
- **A plan is a hypothesis.** The RAG recipe wasn't wrong when it was
  written; it was wrong by the time I got there. Checking took an afternoon
  and saved weeks.

## Next Steps

Memory that persists raises a question memory-less chat never had to answer:
what should a bear *refuse* to remember? That's the current work — a
never-store policy (secrets, other people's private business, credentials,
health details...) enforced in the write path and regression-tested by the
personality eval. After that: Strohsack stops being an only bear — a
character registry, per-character memory scoping, and a polar bear named
Bim Bam are next.

---

*Strohsack AI is a hobby project bringing a beloved plush bear to life as a
conversational character — and a portfolio of AI application engineering
along the way. The public repo runs a generic bear; the family-specific
personality stays private.*
