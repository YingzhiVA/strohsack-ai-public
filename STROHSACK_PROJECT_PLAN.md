# Strohsack AI - Project Plan
**Bringing a Beloved Plush Bear to Life**

*Last Updated: July 6, 2026*

---

## Project Vision

Create an AI-powered conversational agent that embodies the personality of our family's beloved plush bear, Strohsack. The ultimate goal is real-time, voice-based conversation, with the physical implementation integrated into the plush bear itself.

**Secondary Goal:** Build a comprehensive portfolio showcasing AI application development skills, from concept to deployment.

**Public/Private split:** The repository is intended to go public as a portfolio piece. To avoid disclosing real family dynamics, the project ships a **generic personality** publicly while the **family-specific personality** (named relatives, relationship behaviors) lives in a private, gitignored config that is only loaded at home. Personality config is therefore *pluggable*: the engine loads whichever profile is present, and the public demo runs the generic bear. See **Pre-Public Hardening** below.

---

## Background & Context

**Creator Background:**
- Product Manager in tech industry
- Strong Python skills (numpy, pandas, scipy)
- Some OOP knowledge from C# background (10+ years ago)
- Foundational LLM knowledge (deeplearning.ai courses)
- Recently familiarized with GitHub, VS Code, Claude Code
- Rookie in software development process

**Strohsack's Personality:**
- Comprehensive personality profile captured in `personality.json`
- Core traits: lazy but lovable, honey-obsessed, mysterious knowledge, warm and playful
- Claims to learn things in dreams
- **Family relationships are private.** The full profile includes relationship
  dynamics with real family members; these are kept out of the public repo and
  loaded from a separate private config at home (see Project Vision + Pre-Public
  Hardening). The public profile is a self-contained generic bear.

---

## Development Philosophy

1. **Start Simple, Iterate Often** - Begin with minimal viable features, add complexity gradually
2. **Portfolio-Driven Development** - Each milestone should demonstrate new skills
3. **Test Before Moving On** - Validate functionality before adding new features
4. **Document Everything** - Capture learnings, decisions, and challenges
5. **Safety First** - Build in guardrails from the beginning

---

## Project Milestones

### **Phase 0: Foundation** 
**Timeline:** Week 1-2  
**Goal:** Set up infrastructure and simplify the personality

#### Sub-tasks:
1. **Repository Structure Setup**
   - Initialize GitHub repo with proper .gitignore, README
   - Set up virtual environment
   - Create basic project structure
   - Configure development tools

2. **Personality Simplification**
   - Extract ~5 core traits from complex personality.json
   - Create simplified personality prompt (v0.1)
   - Version personality configs for iteration

3. **First "Hello World"**
   - Simple script that generates one Strohsack response using Claude API
   - Validates personality is working
   - Test basic API integration

**Deliverables:**
- ✅ Working GitHub repository
- ✅ Development environment setup
- ✅ Simplified personality config (v0.1)
- ✅ Basic API integration test
- ⬜ First journey blog post (only a template exists at `docs/journey/01-foundation-template.md`)

---

### **Milestone 1: Core Personality Chatbot**
**Timeline:** Week 2-4  
**Goal:** Text-based conversation with distinctive personality

#### Sub-phases:

**1A: Basic Chat Loop** — ✅ DONE (merged PR #1)
- Terminal-based conversation interface (`strohsack.interfaces.cli`)
- Session-based context (no persistence yet) (`conversation.manager.ConversationManager`)
- Basic error handling (`ConfigError`, `StrohsackAPIError`, history rollback on failure)

**1B: Personality Consistency Testing** — ✅ DONE
- Does Strohsack stay in character? → LLM-as-judge harness (`strohsack.eval`)
- Test various conversation topics → 22 probes across 8 categories (`eval/probes.yaml`)
- Refine prompts based on results → run `scripts/run_personality_eval.py`, read report
- Harness built: probes + 8-trait rubric + judge + runner + offline tests (mocked judge)
- Baseline live eval: 0.91 overall, 100% in-character. Weak spots: brevity under
  pressure (wrote a full 500-word essay when asked), curt/cold refusals, long fact answers.
- Prompt iteration #1: added "refuse long/effortful asks", a warm-refusal example, and a
  "facts are quips not lectures" rule. Re-eval: **0.94 overall, 100% in-character**
  (proud_laziness +0.06, warmth +0.06, brevity +0.04, nothing regressed).
- Prompt iteration #2: fixed conversational dead-ends — Strohsack's one-liners were
  funny but gave the human nothing to reply to. Added "Nosy About You" trait (curious
  about people, not effort), land-then-volley response rhythm, and updated example
  responses. New `conversational_volley` eval trait + 2 probes (greet-age,
  emo-child-again). Re-eval: **0.96 overall, 100% in-character**, volley trait 0.99;
  adversarial guardrail holds (self-contained refusals still score high). (PR #10)
- Above the >90% in-character target.
- Code review (PR #5) hardening: robust JSON extraction (raw_decode vs greedy regex),
  per-probe error recovery (failed probes excluded from averages, not counted as 0),
  critical-trait hard-fail gate (a cruel reply can't pass on a high mean), and
  targets-weighted scoring (a probe's intended traits drive its score). 27 tests.

**1C: Simple Web Interface** — ✅ DONE
- Streamlit chat UI (`strohsack.interfaces.web`), run with
  `streamlit run src/strohsack/interfaces/web.py`
- Reuses the M1A core untouched: `load_config` → `StrohsackClient` →
  `ConversationManager`. Per-visitor history lives in `st.session_state`
  (the client is `@st.cache_resource`-shared, since it holds no state).
- Replies **stream** token-by-token (`StrohsackClient.stream_response` +
  `ConversationManager.send_stream`, with the same user-turn rollback on
  failure as `send`). Nicer for the demo video.
- Greeting/farewell moved to `interfaces/__init__.py` so CLI and web share one
  source of truth. Each is a pool of in-character variants picked at random
  (`greeting()` / `farewell()`) so Strohsack rarely repeats himself; the web UI
  holds the chosen line in `st.session_state` so it doesn't flicker across
  Streamlit reruns. Sidebar "new nap" button resets the session (and re-rolls).
- Gradio dropped from `requirements.txt` (Streamlit chosen). 4 new streaming
  tests in `test_conversation.py` (45 total, all passing).

**Key Technical Decisions:**
- LLM: Claude API (Sonnet model)
- Focus: System prompt engineering
- Context: Maintain conversation within session only

**Technical Skills Demonstrated:**
- API integration
- Prompt engineering
- Basic UI development
- Error handling

**Deliverables:**
- ✅ Working CLI chatbot
- ✅ Web-based interface (1C — Streamlit, streaming)
- 🔄 Personality prompt v1.0 (iterating; v0.1 in use, refined via 1B testing)
- ✅ Test suite for personality consistency (1B)
- ✅ Demo video — Milestone 1 web UI demo recorded and embedded in README
- ⬜ Journey blog post: "Building the Core Personality"

---

### **Milestone 2: Memory System**
**Timeline:** Week 5-8  
**Goal:** Persistent memory across sessions

> **Plan revision (June 2026):** The original 2B/2C used the 2023-era RAG recipe
> (embeddings + ChromaDB/FAISS + vector similarity search). Two things made that
> over-engineered for a personal project: (1) claude-sonnet-4-6's 1M context window
> means the entire conversation history fits in context cheaply, making vector
> retrieval unnecessary at family scale; (2) Anthropic's `memory_20250818` tool is
> now first-class — the model can curate its own durable facts via tool calls rather
> than needing a hand-rolled retrieval pipeline. 2B is rewritten to use the agentic
> memory tool; 2C becomes context management and the memory-management UI.

#### Sub-phases:

**2A: Episodic Memory (SQLite)** — ✅ DONE (June 2026)
- `SQLiteMemoryStore`: thread-safe, Protocol-backed (`MemoryStore`), backed by
  gitignored `data/strohsack.db`. Schema: `sessions` + `messages` tables, FK cascade.
- `ConversationManager` updated: optional `store` + `session_id`; loads prior history
  on construction, persists each completed turn (rollback-on-failure preserved for both
  sync and streaming paths).
- CLI: session resume by default, `--new` flag for fresh sessions, `forget` command
  to wipe current session; resume banner shown when history exists.
- Model bumped to `claude-sonnet-4-6` (1M context, adaptive thinking); personality
  eval confirmed 0.96 baseline fully preserved.
- 74 tests passing (14 new store tests, 7 new persistence integration tests).
- **Note:** Streamlit web interface (`web.py`) was not updated in 2A (still M1A
  in-memory at that point). ✅ Wired to the persistent memory core in June 2026 —
  see the 2C deliverable below.

**2B: Agentic Memory Tool (durable facts)**
- Give Strohsack the `memory_20250818` / `BetaAbstractMemoryTool` so he reads and
  writes durable facts himself via tool calls (things he learns about you, preferences,
  recurring topics).
- Memory files written to gitignored `data/memory/` — never tracked or published.
- Add the agentic tool loop to `StrohsackClient`; start with the non-streaming CLI
  path, then adapt streaming.
- Add schema versioning to `SQLiteMemoryStore` before extending the schema here
  (deferred from M2A code review).
- **Outcome (benchmarked):** built on `memory_20250818` / `BetaLocalFilesystemMemoryTool`
  and it works, but the latency benchmark (`scripts/bench_memory.py`, sonnet-4-6) exposed
  a structural cost that reshapes 2C — see below. In short: the builtin tool reads
  `/memories` on *every* turn (2 round-trips even on empty memory, 3 on a populated read
  ≈23s, 4 on read+write ≈34s), the read is **server-driven** (the SDK sends only
  `{"type":"memory_20250818","name":"memory"}` — no client-side prompt injection), and a
  system-prompt "don't re-read" nudge had **zero effect** (A/B'd: round-trips identical).
  So the read cost can't be tuned away with prompts.

**2C: Fast Memory Architecture, Context Management & Memory UI**

- **Memory architecture — inject-on-read, tool-on-write (the headline change).** ✅ DONE
  Implemented: durable facts live in a SQLite `facts` table (schema v2, migrated in place);
  `StrohsackClient` injects stored facts into the system prompt each turn and offers a
  custom `remember(note)` tool via the tool runner; the builtin `memory_20250818` tool is
  gone. The plain (no-fact-store) path is preserved for the personality eval and tests.
  `forget` now also clears the session's facts. 100 tests passing.
  Replace the always-on builtin memory tool with a split that matches how reads and
  writes actually behave:
  - **Reads → inject, don't tool-call.** Load the memory file ourselves each turn and
    place it in the system prompt. Memory is then *always present at zero extra
    round-trips* — no cue detection, and (crucially) no false negatives where Strohsack
    blanks on something he should know. "Do you remember?" costs the same as "hello".
  - **Writes → a small custom tool.** Expose a plain user-defined `remember()`/update
    tool via the tool runner (not the builtin `memory_20250818`, whose server-side
    behavior forces the pre-read). A custom tool has no forced read, so it adds a
    round-trip *only* on turns where Claude decides to save something — and the model is
    a far better judge of "worth keeping" than any keyword cue.
  - **Result:** normal chat 1 call; references-the-past 1 call *and always correct*;
    reveals-a-new-fact 2 calls. (vs builtin: 2 / 3 / 4.)
  - **Rejected alternative — gating reads by user cues** ("do you remember"): brittle
    keyword matching false-negatives the core feature; detecting an implicit
    "he-should-know" tone needs its own classifier call; and it solves reads while
    leaving writes unaddressed. Injection makes reads *free* rather than *rare* — strictly
    better on cost and correctness. (This was considered and set aside, June 2026.)
- **Prompt caching (secondary lever).** ✅ DONE — `system` is now sent as content blocks
  with `cache_control` on the stable persona block (GA, no beta header); durable facts go in
  a separate block *after* the breakpoint so saving a fact doesn't invalidate the cached
  persona prefix (tools render before `system`, so the `remember()` schema is cached too).
  Applies to both client paths. **Verified live:** the ~2.3K-token persona prefix writes to
  cache on the first call and is served at ~0.1x input cost on subsequent calls within the
  5-min TTL (cache_read=2288). Measured at 2295 persona-only / 2955 with the tool — both above
  Sonnet 4.6's 2048-token cache minimum, so it actually engages. As predicted, this trims
  *input* cost (most valuable for the rapid-fire eval and web turns) but does **not** touch
  round-trips or output time — the secondary lever it was always framed as.
- **Fact consolidation.** ✅ DONE — a CLI `tidy` (`consolidate`) command has the model
  rewrite the durable-fact list: merge near-duplicates, drop stale/superseded notes,
  tighten wording (structured output → reliable list back). Consolidated facts are stored
  session-less (NULL) — promoted to long-term memory, no longer per-session forgettable
  (only a full wipe clears them). This is a *quality* win independent of token pressure:
  cleaner, non-contradictory facts → sharper recall and a smaller injected block.
  Verified live (6 messy facts → 4 clean).
- **Episodic rolling summarization — deferred (not premature-built).** Compressing old
  conversation *turns* into a running summary only pays off under token pressure we don't
  have (1M context, short sessions, cached prefix). The `--stats` readout is the trigger:
  build this when real sessions show input tokens climbing, not before. (Build-vs-buy when
  we do: Anthropic's server-side compaction beta vs. hand-rolled — server-side needs
  content-block history and triggers at 150K tokens.)
- **Memory management UI:** view/edit what Strohsack remembers (episodic history + the
  curated fact file). Good for portfolio demos and debugging.
- **Fix `forget` (known issue from 2B code review):** ✅ DONE — `forget` now clears the
  session's durable facts (`store.clear_facts(session_id)`) alongside the episodic history,
  scoped to the current session so facts from other conversations survive. A full
  memory-wipe action belongs to the memory UI below.
- `docs/architecture/memory-system.md`.

**Key Technical Decisions:**
- Episodic layer: SQLite (local, private, gitignored) — no external DB needed at
  personal scale.
- Semantic layer: model curates its own durable facts (no hand-rolled embeddings +
  vector search). 2B proved this out with the builtin `memory_20250818` tool; 2C moves
  to **inject-on-read, tool-on-write** because the builtin tool's server-driven every-turn
  read is too slow (benchmarked ≈23–34s) and can't be tuned away with prompts.
- 1M context window makes always-*injecting* memory + recent history cheap (no retrieval
  round-trips); rolling summarization bounds cost as memory and sessions grow. Prompt
  caching is a secondary trim on input cost, not the primary latency lever.
- All memory data lives in gitignored `data/` — never tracked, never published.

**Technical Skills Demonstrated:**
- Database design & management (SQLite, schema design, thread safety)
- Agentic tool use (model-driven memory curation)
- Context window management & prompt caching
- State management

**Deliverables:**
- ✅ Persistent episodic memory (2A)
- ✅ Agentic fact memory with tool use (2B — builtin `memory_20250818`; benchmarked, found too slow for default use)
- ✅ Inject-on-read / tool-on-write memory architecture, replacing the always-on builtin tool (2C)
- ✅ Fact consolidation — model-driven `tidy` command (merge near-dups, drop stale notes), verified live (2C)
- ⬜ Episodic rolling summarization — deferred until `--stats` shows real token pressure (2C)
- ✅ Prompt caching on the stable prefix (secondary) — cache_control on the persona block, verified live (cache_read 2288 tokens) (2C)
- ✅ CLI token/cache observability — `--stats` per-turn readout + `stats` command (input/cache-read/cache-write/output, hit rate, est. cost & savings); doubles as a silent-cache-regression guard (2C)
- ✅ Memory management UI — Streamlit 🧠 Memory page over the persisted SQLite store: view/delete durable facts, browse & delete episodic sessions, full-wipe ("forget everything"). Reads/writes the same DB the CLI uses. (2C)
- ✅ Web chat wired to the memory core (June 2026) — the Streamlit chat now mirrors the CLI's wiring (`fact_store` + `session_id` on the client, `store` + `session_id` on the manager): episodic turns persist and durable facts are injected/saved via `remember()`. Each browser load starts a fresh episodic thread (single-user; per-guest scoping is Milestone 3), while cross-session durable facts carry the "he remembers me" story; "New nap" opens another fresh thread. (2C)
- ✅ Architecture documentation (`docs/architecture/memory-system.md`) — memory deep dive: two layers, inject-on-read/tool-on-write, caching, consolidation, the management UI, data model; `system-design.md` reconciled to match
- ⬜ Demo video showing memory in action
- ⬜ Journey blog post: "Implementing AI Memory"

---

### **Milestone 2.5: Safety & Guardrails** *(Parallel Development)*
**Timeline:** Ongoing from Week 5  
**Goal:** Ensure safe, appropriate conversations

#### Components:
- **Content Filtering**
  - Inappropriate language detection
  - Topic boundaries
  - Family-friendly enforcement

- **Privacy Controls**
  - What memories should never be stored
  - Confidential information handling
  - Data retention policies

- **Conversation Boundaries**
  - Staying in character
  - Refusing harmful requests
  - Appropriate behavior with children

- **Public/Private Data Hygiene**
  - No real family details in the public repo, code, configs, or committed history
  - Family relationship data is private-config-only (see Pre-Public Hardening)
  - Generic personality must be self-contained (no dangling references to relatives)

- **Testing**
  - Real-world usage scenarios (private build at home; generic build for public demos)
  - Edge case discovery
  - User feedback integration

**Technical Skills Demonstrated:**
- Safety engineering
- Content moderation
- Privacy by design
- User testing methodologies

> **Status (July 2026):** Not started as a milestone. Partial groundwork exists
> elsewhere: the eval harness includes adversarial probes verifying in-character
> refusals (1B), and public/private data hygiene was fully handled by Milestone
> 3.6. The deliverables below are otherwise unbuilt.

**Deliverables:**
- ⬜ Safety guidelines document
- ⬜ Content filtering system
- ⬜ Privacy policy and controls
- ⬜ Test results from family members

---

### **Milestone 3: Access Control & Guest Sessions** *(Deferred — June 2026)*
**Timeline:** Week 9-12  
**Goal:** Control *who* can chat with Strohsack, and give each guest their own
isolated session and memory — without per-person personality changes.

> **Deferred (June 2026):** Guest sessions are pushed back in favor of building
> out more single-user Strohsack features first; this isn't shared with others
> yet, so per-guest access control and isolation aren't on the critical path. As
> a step toward this, the **web chat is now wired to the persistent memory core**
> (episodic threads + durable facts, same store as the CLI — see Milestone 2C
> deliverables): a clean single-user baseline that the per-guest scoping in 3C
> will later key by guest id. Resume here when opening Strohsack up to guests.

> **Pivot (June 2026):** This milestone was originally "Multi-User &
> Relationships," with Strohsack modulating personality per recognized family
> member. That revealed real family dynamics, which is a problem for a repo
> intended to go public. Relationship modulation is
> now a **private, at-home-only** feature driven by the private personality config
> (see Project Vision). The public milestone is reframed around **access control
> and guest-session isolation** — same engineering depth (auth, sessions, per-user
> memory, system design), no personal disclosure. Strohsack is the same warm, lazy,
> honey-obsessed bear to *every* guest.

#### Sub-phases:

**3A: Invitation & Credential System**
- Issue per-guest invitation links / credentials (signed tokens)
- Token validation, expiry, and revocation
- Optional: rate limiting per credential

**3B: Guest Sessions & Identity**
- Lightweight guest accounts (no real-world PII required — a display name is enough)
- Session lifecycle: create, resume, expire
- "First-time guest" vs "returning guest" greeting distinction
- Guest profile is generic (preferences, display name) — *not* a relationship role

**3C: Per-Guest Memory Isolation**
- Each guest's memory (from Milestone 2) is scoped to that guest
- No cross-guest leakage; one guest cannot see another's conversations
- Privacy controls: a guest can clear/export their own memory
- (Shared/family memory stays in the private at-home build only)

**3D: Admin / Host View**
- See active invitations and sessions
- Revoke a credential
- Basic per-guest usage (counts, last seen) — no conversation content exposed by default

**Key Technical Decisions:**
- Token scheme: signed, stateless invitations (e.g. itsdangerous / JWT) vs. DB-backed
- Session store (SQLite/Redis) and memory scoping keyed by guest id
- All access-control state is generic — no relationship graph in the public repo
- Relationship-aware behavior, if ever surfaced, comes from the private config only

**Technical Skills Demonstrated:**
- Authentication & authorization
- Session management & token security
- Multi-tenant data isolation (privacy by design)
- System design at scale

**Deliverables:**
- ⬜ Invitation-link / credential issuance + validation
- ⬜ Guest session lifecycle
- ⬜ Per-guest memory isolation
- ⬜ Admin/host view for invitations & sessions
- ⬜ Demo: inviting a guest, chatting, revoking access
- ⬜ Journey blog post: "Access Control for a Personal AI"

---

### **Milestone 3.6: Pre-Public Hardening** *(Gate before making the repo public)*
**Timeline:** Before first public release  
**Goal:** Ensure no real family data is exposed in the public repository — in
working files **or** in git history.

> **Why this is its own milestone:** the family-specific data once lived in
> `src/config/personality.json` and was described in this plan — and it was
> present in **every commit, starting from the very first one**. Deleting it in a
> new commit is *not enough*: it remains recoverable in history. So going public
> required both scrubbing the working tree **and** a clean break from history.

#### Components — all done (June 2026):

**A: Pluggable personality (generic vs. private)** — ✅ DONE
- `config_loader.load_personality_profile()` selects a profile: an explicit
  path/`STROHSACK_PERSONALITY` env var loads as-is; otherwise the public
  `personality.json` is the base, with a private overlay deep-merged on top when
  present.
- `personality.json` (public) is scrubbed of all relationship data and is
  self-contained — the generic bear, with no dangling references to relatives.
- `personality.private.json` (the at-home overlay) holds all relationship
  dynamics, family interaction contexts, family teasing data, and the
  relationship-specific behavioral patterns — and is **gitignored**. The public
  build never ships it, so it auto-runs the generic bear.

**B: Repository decision — fresh public repo** — ✅ DONE
- Chose **Option 1**: a *separate* public repo built from a squashed snapshot of
  the scrubbed tree (no historical commits carried over). This private repo stays
  as the full-history working repo. (History rewrite via `git filter-repo` was the
  rejected alternative — riskier, rewrites every commit anyway.)
- Live at **https://github.com/YingzhiVA/strohsack-ai-public**.

**B2: Ongoing publishing workflow** — ✅ DONE
- The public repo is kept current with a **scripted re-snapshot**, not manual
  steps. `scripts/publish_public_snapshot.py` exports tracked files of
  `origin/main` (private overlay structurally excluded), runs the scan gate
  against the staged export, and force-pushes a single squashed commit to the
  public repo — aborting on any scan hit. `--dry-run` previews; the push asks for
  confirmation. Run it when a milestone lands. See `scripts/README.md`.

**C: Pre-publish scan (automated)** — ✅ DONE
- `scripts/check_no_private_data.py` greps the git-tracked working tree for the
  sensitive terms and structural keys; exits non-zero if any are found. Respects
  `.gitignore`, so it never scans the private overlay. Run as the final gate
  before publishing.

**D: Sanitize prose** — ✅ DONE
- `README.md` (already clean), `SETUP_GUIDE.md`, and this plan describe the
  *generic* bear and the public/private split conceptually — no named relatives.

**Deliverables:**
- ✅ Pluggable personality loader + scrubbed public `personality.json`
- ✅ Private `personality.private.json` (gitignored) with all family data
- ✅ Repo-publish approach chosen and documented (fresh public repo, squashed)
- ✅ Public repo published (https://github.com/YingzhiVA/strohsack-ai-public)
- ✅ Scripted publishing workflow (`scripts/publish_public_snapshot.py`)
- ✅ Automated pre-publish scan (`scripts/check_no_private_data.py`)
- ✅ Sanitized README, setup guide, and plan

---

### **Milestone 3.5: Analytics Dashboard** *(Optional Enhancement)*
**Timeline:** Week 11-12  
**Goal:** Insights into Strohsack's performance and usage

#### Features:
- **Conversation Insights**
  - Most discussed topics
  - Conversation length/frequency
  - User engagement metrics

- **Memory Graph Visualization**
  - Relationship between memories
  - User connection maps
  - Memory clusters

- **Personality Consistency Metrics**
  - In-character percentage
  - Trait expression frequency
  - Behavior pattern analysis

- **User Engagement Patterns**
  - Active users
  - Conversation times
  - Feature usage

**Technical Skills Demonstrated:**
- Data visualization
- Analytics implementation
- Dashboard development
- Metrics design

**Deliverables:**
- ⬜ Analytics dashboard
- ⬜ Visualization examples
- ⬜ Insights documentation

---

### **Milestone W: Strohsack World** *(New track — July 2026)*
**Timeline:** Open-ended; sprints sized at 1–2 hobby-weeks  
**Goal:** Expand Strohsack into a small explorable world: a cast of characters who
banter with the user *and* each other, pixel-art scenes that reflect the
conversation, and eventually an interactive world you can poke (click a honey pot →
Strohsack reacts).

> **Why a new track (July 2026):** The project branches here. Voice (M4) and plush
> hardware (M5) are one *body* for the character brain; a pixel world is another.
> Both consume the same Python character engine — the world track is just a new
> entry in `interfaces/`. M4/M5 are **shelved** (not deleted — see their sections
> below) in favor of this track.

> **Load-bearing architecture rules (from the July 2026 feasibility analysis):**
> 1. **No runtime image generation.** Pixel assets (sprites, rooms, props,
>    animation loops) are pre-made; the LLM emits a structured **scene directive**
>    (`{location, character_state, mood, props[]}`) alongside dialogue, and a
>    renderer maps directives to assets. The LLM picks from a menu; the menu is
>    the asset library.
> 2. **LLM as brain, state machine as body.** Ambient world behavior (wandering,
>    napping, fishing) is scripted state machines at zero API cost; the model is
>    invoked only on interaction or deliberately staged scenes.
> 3. **Instant canned reaction + async LLM line.** Clicks get a ~100ms scripted
>    animation response; the in-character dialogue line arrives a moment later.
> 4. **Streamlit ends at W3.** A persistent animated canvas needs a real frontend
>    (canvas page + FastAPI/WebSocket backend). The core engine is already
>    interface-agnostic, so this is additive, not a rewrite.

#### Epic W1: The Cast *(pure Python — no new skills)*
Characters: Bim Bam (polar bear "bro", banter partner), guests Giuseppe
(monster-movie-loving wild pig) and Mapache (ancient, stingy, Catalan-speaking
raccoon), plus a cheap template for future minor characters.

- **W1.1 — Character abstraction.** `Character` = profile + prompt + memory scope;
  registry over `characters/*.json`; public/private overlay reused per character;
  CLI `--character`; schema v3 (`character_id` on sessions + facts).
  *Done when: a stub Bim Bam chats in the CLI and his facts don't leak into
  Strohsack's.*
- **W1.2 — Bim Bam v1, eval-backed.** Full profile (he needs his own obsession, as
  honey is to Strohsack); eval harness generalized to per-character rubrics/probes.
  *Done when: Bim Bam >0.9 in-character on his own rubric; Strohsack's 0.96
  baseline untouched.*
- **W1.3 — Guest characters.** Giuseppe + Mapache as lighter "guest tier" profiles;
  language-consistency eval trait for Mapache's Catalan.
  *Done when: 4 chattable, eval-baselined characters.*

#### Epic W2: The Banter *(multi-agent orchestration — the portfolio piece)*
- **W2.1 — Two-bear banter MVP.** `SceneOrchestrator`: alternating API calls with
  each bear's cached persona, seeded topic, stop conditions (max turns, natural
  close, token budget); CLI transcript; `--stats` instrumentation from day one.
- **W2.2 — User joins the scene.** 3-way chat; turn allocation by heuristics first
  (addressed-by-name), Haiku "director" as fallback.
- **W2.3 — Quality & cost hardening.** Personality-bleed eval on group transcripts;
  A/B the core architecture question with the harness: one-call-per-character
  (authentic, N× cost) vs. single director call writing the exchange (cheap,
  bleed-prone); try Haiku for guest characters. Documented TDR at the end.

#### Epic W3: The Stage *(pixel scenes — the new-skills epic)*
- **W3.0 — Engine spike (timeboxed: 1 week hard).** Same toy built twice — one
  room, Strohsack idle loop, click-a-prop logs an event — in **Phaser 3 (JS)** and
  **Godot 4 (GDScript)**. Decide on: debuggability, chat-UI integration,
  deploys-as-a-link. Written up as a TDR. (Working lean: Phaser + FastAPI, because
  the product is chat-first with a stage; Godot if it drifts toward real game
  mechanics.)
- **W3.1 — Asset pipeline v0.** Starter room from a CC0/cheap pack (Kenney,
  itch.io); Strohsack sprite with idle/walk/sleep/talk loops (own work — Aseprite,
  optionally AI-drafted then hand-cleaned); 3–4 props. Art workflow documented.
- **W3.2 — Scene directive protocol (the load-bearing spec).** Structured output
  `{dialogue, scene:{location, character_state, mood, props[]}}` validated against
  a schema that enumerates *only existing assets*; renderer maps directives to
  sprites with graceful fallback. This protocol is the contract between everything
  Python and everything visual.
- **W3.3 — Chat + stage MVP.** FastAPI + WebSocket; canvas above, chat below;
  memory core wired in. Mention dreaming of a honey waterfall → he's lounging
  beside one. *Deliverable: the demo video that justifies the epic.*

#### Epic W4: The World *(interactivity & ambient life)*
- **W4.1 — Click → reaction.** Hotspots; instant canned animation + async
  in-character line; click events enter the conversation/memory ("not a honey
  thief, are you?" — and he *remembers* you poking the pot).
- **W4.2 — Ambient life (zero-LLM).** Per-character state machines + simple daily
  schedule. *Done when: the world is visibly alive with the API bill at zero while
  idle.*
- **W4.3 — Banter on stage.** W2 scenes rendered visually; watch or butt in.
- **W4.4 — Persistence, guests, deploy.** World state in SQLite; per-guest scoping
  hooks (deferred Milestone 3 re-enters here); deploy to a small VPS behind the
  invitation system.

**Key Technical Decisions:**
- Rendering stack: Phaser 3 + FastAPI/WebSocket vs. Godot 4 — decided by the W3.0
  spike, not on paper.
- Scene directives (structured output) instead of runtime image generation.
- Cost control: hard scene budgets, Haiku for guest characters, scripted ambient
  behavior; no autonomous background LLM scenes.
- Epics W1/W2 are pure Python and de-risk the product (is a multi-character world
  fun?) before investing in the rendering stack.

**Known Risks:**
- Scope creep is the project risk — W1/W2 deliver value even if W3 never ships;
  W3.0 is a spike, not a commitment.
- Art is the schedule risk — buy everything that isn't a main character.
- Banter cost is the money risk — fully controllable via budgets; instrument first.
- Safety scope grows (kids clicking everything; Mapache's "stingy" shtick needs the
  same warm-refusal discipline from 1B). M2.5 guardrails apply per-character.
- Pre-public hygiene: new character profiles need the public/private overlay
  treatment before the next `publish_public_snapshot.py` run.

**Technical Skills Demonstrated:**
- Multi-agent orchestration & LLM-to-LLM quality evaluation
- Structured output as a UI contract (scene directives)
- Real-time web (FastAPI, WebSockets) + canvas rendering
- Game-loop fundamentals (sprites, state machines, event dispatch)
- Cost engineering for interactive LLM systems

**Deliverables:**
- ⬜ Character registry + per-character memory (W1)
- ⬜ Eval-baselined cast: Bim Bam, Giuseppe, Mapache (W1)
- ⬜ Banter scenes with budgets + bleed eval + architecture TDR (W2)
- ⬜ Rendering-stack TDR from the engine spike (W3.0)
- ⬜ Scene-directive protocol + chat-with-stage MVP + demo video (W3)
- ⬜ Interactive, ambient, persistent world; guest deploy (W4)
- ⬜ Journey blog posts: "One Bear Becomes a Cast", "Making Bears Argue",
  "A Stage for Strohsack"

---

### **Milestone 4: Voice Interface** *(Shelved — July 2026)*

> **Shelved (July 2026):** Voice and hardware integration (M4/M5) are set aside in
> favor of the Strohsack World track (Milestone W) — reservations about moving
> toward hardware, and the world track exercises the same character engine with a
> faster feedback loop. The sections are kept intact below as the record of the
> original plan; resume here if a voice/physical body for Strohsack becomes
> appealing again.

**Timeline:** Week 13-16  
**Goal:** Speech-to-text and text-to-speech integration

#### Sub-phases:

**4A: Speech-to-Text Integration**
- OpenAI Whisper or similar service
- Audio input handling
- Transcription accuracy testing

**4B: Text-to-Speech with Personality**
- Select voice that matches Strohsack
- ElevenLabs, Azure TTS, or similar
- Emotion/prosody control
- Voice personality matching

**4C: Voice Activity Detection**
- When to start listening
- When to stop listening
- Background noise handling
- Turn-taking logic

**4D: Real-Time Conversation Flow**
- Minimize latency (critical!)
- Handle interruptions
- Natural pauses and pacing
- Conversational rhythm

**Key Technical Decisions:**
- STT/TTS: Cloud vs. local processing
- Latency optimization is crucial
- Voice selection and customization
- Real-time audio processing

**Challenge:** This is where complexity jumps significantly!

**Consider Adding:**
- **Milestone 4.5: Wake Word Detection**
  - "Hey Strohsack!" trigger
  - Always-listening mode
  - Power efficiency

**Technical Skills Demonstrated:**
- Audio processing
- Real-time systems
- Latency optimization
- Streaming data handling
- Voice interface design

**Deliverables:**
- ⬜ Working STT system
- ⬜ TTS with personality
- ⬜ Voice activity detection
- ⬜ Real-time conversation demo
- ⬜ Performance benchmarks
- ⬜ Journey blog post: "From Text to Voice"

---

### **Milestone 5: Physical Integration** *(Shelved — July 2026)*

> **Shelved (July 2026):** See the note on Milestone 4 — the voice/hardware track
> is paused in favor of Milestone W (Strohsack World). Kept intact as a record.

**Timeline:** Week 17-20  
**Goal:** Deploy to hardware and integrate with plush bear

#### Sub-phases:

**5A: Hardware Setup**
- Raspberry Pi or similar device
- Microphone selection and testing
- Speaker integration
- Power supply design

**5B: Connectivity & Power Management**
- Bluetooth speaker/mic connection
- Battery life optimization
- Charging solution
- Power-saving modes

**5C: Physical Form Factor**
- Bowtie speaker concept
- Sewing/integration into plush
- Durability testing
- Aesthetic considerations

**5D: Reliability & Offline Fallbacks**
- Offline capabilities
- Error recovery
- Graceful degradation
- Maintenance procedures

**Key Technical Decisions:**
- Hardware platform selection
- Power management strategy
- Connectivity approach
- Physical mounting solution

**Challenges:**
- Space constraints
- Power consumption
- Heat dissipation
- Durability and washability (if applicable)

**Technical Skills Demonstrated:**
- Hardware integration
- Embedded systems
- IoT development
- Physical product design
- System reliability engineering

**Deliverables:**
- ⬜ Working hardware prototype
- ⬜ Physical integration with plush
- ⬜ Reliability testing results
- ⬜ Final demo video
- ⬜ Hardware documentation
- ⬜ Journey blog post: "Bringing Strohsack to Physical Life"

---

## Technical Stack Summary

### Core Technologies:
- **Language:** Python 3.10+
- **LLM:** Claude API (Anthropic)
- **Web Framework:** Streamlit or Gradio (Phase 1), potentially FastAPI later
- **Database:** SQLite → PostgreSQL (as needed)
- **Memory Tool:** Anthropic `memory_20250818` (agentic fact curation, replaces planned RAG/embeddings)

### World Track (Milestone W):
- **Backend:** FastAPI + WebSocket (replaces Streamlit for the world interface)
- **Rendering:** Phaser 3 (JS) or Godot 4 (GDScript) — decided by the W3.0 spike
- **Art:** Aseprite for main characters; CC0/purchased asset packs (Kenney,
  itch.io) for rooms/props; optional AI-assisted drafts (hand-cleaned)
- **Scene protocol:** structured output (JSON scene directives) over pre-made assets
- **Cost tiers:** Sonnet for lead characters, Haiku for guests/director

### Voice Technologies (Milestone 4+) — *shelved July 2026*:
- **STT:** OpenAI Whisper
- **TTS:** ElevenLabs or Azure TTS
- **Audio:** PyAudio, sounddevice

### Hardware (Milestone 5) — *shelved July 2026*:
- **Platform:** Raspberry Pi 4 or similar
- **Connectivity:** Bluetooth
- **Audio:** USB microphone, Bluetooth speaker

### Development Tools:
- **IDE:** VS Code with Claude Code
- **Version Control:** GitHub
- **Environment:** Python venv or conda
- **Testing:** pytest
- **Documentation:** Markdown, Jupyter notebooks

---

## Repository Structure

```
strohsack-ai/
├── README.md                          # Project overview, demo videos
├── STROHSACK_PROJECT_PLAN.md         # This document
├── docs/
│   ├── journey/                       # Development blog posts
│   │   ├── 01-foundation.md
│   │   ├── 02-personality-design.md
│   │   ├── 03-memory-implementation.md
│   │   └── ...
│   ├── architecture/                  # Technical decisions
│   │   ├── system-design.md
│   │   ├── memory-system.md
│   │   ├── personality-engine.md
│   │   └── voice-interface.md
│   │                                  # (learnings kept in a private, gitignored folder)
│   └── api/                           # API documentation
│       └── endpoints.md
├── src/
│   ├── strohsack/
│   │   ├── __init__.py
│   │   ├── personality/               # Personality engine
│   │   │   ├── __init__.py
│   │   │   ├── core.py
│   │   │   ├── prompts.py
│   │   │   └── config.py
│   │   ├── memory/                    # Memory management
│   │   │   ├── __init__.py
│   │   │   ├── storage.py
│   │   │   ├── retrieval.py
│   │   │   └── embeddings.py
│   │   ├── conversation/              # Conversation logic
│   │   │   ├── __init__.py
│   │   │   ├── manager.py
│   │   │   └── context.py
│   │   ├── interfaces/                # UI/Voice interfaces
│   │   │   ├── __init__.py
│   │   │   ├── cli.py
│   │   │   ├── web.py
│   │   │   └── voice.py
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── api_client.py
│   │       └── config_loader.py
│   └── config/
│       ├── personality_v0.1.json      # Versioned personalities
│       ├── personality_v0.2.json
│       ├── personality_v1.0.json
│       └── settings.yaml
├── tests/
│   ├── test_personality.py
│   ├── test_memory.py
│   ├── test_conversation.py
│   └── test_integration.py
├── notebooks/                         # Exploration & prototyping
│   ├── personality_testing.ipynb
│   ├── memory_experiments.ipynb
│   └── voice_testing.ipynb
├── demos/                             # Video demos, screenshots
│   ├── milestone1_demo.mp4
│   ├── milestone2_demo.mp4
│   └── screenshots/
├── scripts/                           # Utility scripts
│   ├── setup_db.py
│   ├── migrate_data.py
│   └── deploy.sh
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
└── setup.py
```

---

## Documentation Strategy

### 1. GitHub Repository (Primary Portfolio Piece)

**README.md Structure:**
- Project overview with compelling hook
- Demo video/GIF prominently featured
- Key features and technical highlights
- Quick start guide
- Links to detailed documentation
- Technology stack
- Development journey link
- Contact/social links

### 2. Journey Blog (`/docs/journey/`)

Write a detailed blog post for each milestone:
- **What:** Goal and scope
- **Why:** Motivation and decisions
- **How:** Technical approach and implementation
- **Challenges:** Problems encountered
- **Solutions:** How you solved them
- **Learnings:** Key takeaways
- **Code Highlights:** Interesting snippets with explanations
- **Next Steps:** What's coming next

### 3. Architecture Documentation (`/docs/architecture/`)

Technical decision records (TDRs):
- System design with diagrams
- Technology choices and rationale
- Data flow and architecture
- Trade-offs considered
- Scalability considerations
- Security and privacy design

### 4. Learnings Documentation (private)

Deep dives into specific topics, kept in a **private, gitignored** folder
(not published with the public repo):
- Prompt engineering techniques
- RAG implementation best practices
- Voice interface optimization
- Hardware integration challenges

### 5. Visual Demos

For each milestone:
- **2-3 minute demo video** showing functionality
- **Screenshots** of UI/interface
- **Architecture diagrams** (draw.io, Excalidraw)
- **Demo GIFs** for README

Upload videos to YouTube or host on GitHub.

### 6. External Blog Posts (Optional but Valuable)

Consider publishing on Medium, Dev.to, or personal blog:
- "Building an AI Personality: Lessons from Bringing a Plush Bear to Life"
- "Implementing RAG for Personal AI Memories"
- "From Product Manager to AI Developer: My Learning Journey"
- "The Challenges of Voice Interface Design"
- "Hardware Integration: Bringing AI into the Physical World"

---

## Success Metrics

### Technical Metrics:
- **Personality Consistency:** >90% in-character responses
- **Memory Accuracy:** >95% fact recall accuracy
- **Response Latency:** <2 seconds text, <3 seconds voice
- **User Engagement:** Average conversation length >10 exchanges
- **System Reliability:** >99% uptime (when deployed)

### Portfolio Metrics:
- Comprehensive documentation for all milestones
- Clean, well-commented code
- Test coverage >70%
- Professional demo videos for each milestone
- Active development history (regular commits)

### Learning Metrics:
- Successfully implement 5+ new technologies
- Build portfolio piece from scratch to deployment
- Demonstrate software engineering best practices
- Show iterative development process

---

## Risk Management

### Technical Risks:
- **API Costs:** Monitor usage, implement caching
- **Latency Issues:** Profile early, optimize aggressively
- **Hardware Limitations:** Test hardware early, have backup plans
- **Privacy Concerns:** Build privacy controls from the start

### Project Risks:
- **Scope Creep:** Stick to milestone plan, resist temptation to add features
- **Time Management:** Set realistic timelines, okay to adjust
- **Technical Debt:** Refactor regularly, don't let it accumulate
- **Perfectionism:** Good enough to move forward is better than perfect and stuck

### Mitigation Strategies:
- Regular code reviews (even self-review)
- Weekly progress checks
- Document decisions as you make them
- Get early feedback from family
- Build MVPs, iterate based on real use

---

## Next Immediate Steps

**Done:**
1. **Set up repository structure** ✅
2. **Configure development environment** ✅
3. **Simplify personality.json to v0.1** ✅
4. **Write first system prompt** ✅
5. **Get Claude API key** ✅
6. **Build "Hello Strohsack" test** ✅ (`scripts/hello_strohsack.py`)
7. **Implement basic CLI chat (Milestone 1A)** ✅ (merged PR #1)

**Done:**
8. **Milestone 1B — personality consistency testing** ✅ (LLM-as-judge harness; 0.96 overall, 100% in-character after 2 rounds of prompt iteration)
9. **Milestone 1C — Streamlit web interface** ✅ (streaming chat reusing the M1A core)
10. **Prompt iteration #2 — conversational follow-through** ✅ (volley behavior, 0.99 on new conversational_volley trait; PR #10)
11. **Architecture documentation** ✅ (`docs/architecture/system-design.md` — describes the M1 system as built; replaced the stale template; PR #11)

**Done:**
12. **Demo video for Milestone 1** ✅ (embedded in README)
13. **Milestone 2A — episodic memory (SQLite)** ✅ (session resume/forget, model bump to sonnet-4-6, 74 tests)
14. **Milestone 2B — agentic memory tool** ✅ (durable facts via `memory_20250818`; schema versioning added, 86 tests, latency benchmarked)
15. **Milestone 2C — inject-on-read / tool-on-write memory** ✅ (replaced the always-on builtin tool; SQLite `facts` table, custom `remember()` tool, `forget` clears facts, 106 tests; PR #17 merged)

16. **Milestone 2C — prompt caching** ✅ (`cache_control` on the persona block; verified live, cache_read 2288 tokens)
17. **Milestone 2C — CLI token/cache observability** ✅ (`--stats` + `stats` command; cache-regression guard)
18. **Milestone 2C — fact consolidation** ✅ (model-driven `tidy` command; episodic summarization deferred until --stats shows token pressure)
19. **Milestone 2C — memory management UI** ✅ (Streamlit 🧠 Memory page over the persisted store: view/delete facts, browse/delete sessions, full wipe; `list_facts`/`delete_fact` store methods + tests)

**Up next:**
20. **Sprint W1.1 — character abstraction** ⬜ (`Character` registry, per-character
    memory scoping via schema v3, CLI `--character`; stub Bim Bam — see Milestone W)
21. **First journey blog post** ⬜ (only a template exists at `docs/journey/01-foundation-template.md`)

---

## Notes & Reflections

*Use this section to capture thoughts, pivots, and insights as the project progresses.*

### Key Learnings:
- **Milestone 1A (text chat):** Built config loader, Anthropic client wrapper,
  session conversation manager, CLI REPL, and a smoke script. A `Responder`
  Protocol decouples `ConversationManager` from the concrete API client, so the
  manager is testable without network access and the memory layer (M2) can slot
  in later.
- **Code review caught real bugs:** history must roll back the user turn if the
  API call fails (otherwise two consecutive user turns break the next request);
  prompt-file path must be package-relative, not repo-root-relative, to survive
  `pip install`. Worth running review before merging each milestone.

### Major Pivots:
- **June 2026 — Public/private personality split.** Decided to make the repo
  public as a portfolio piece. To avoid disclosing real family dynamics, Milestone
  3 was reframed from "Multi-User & Relationships" (per-family-member personality
  modulation) to "Access Control & Guest Sessions" (invitation links, guest
  sessions, per-guest memory isolation). Family relationship behavior moves to a
  private, gitignored personality config loaded only at home; the public build runs
  a generic bear. Added Milestone 3.6 (Pre-Public Hardening) because family terms
  live in every commit since the first, so a fresh public repo or history rewrite
  is required — not just file deletion.
- **July 2026 — Strohsack World; voice/hardware shelved.** The project branches
  from "one bear, heading toward a physical body" to "a cast in a pixel world."
  New Milestone W: multi-character cast (Bim Bam, Giuseppe, Mapache),
  character-to-character banter, pixel-art scenes driven by LLM scene directives,
  and eventually an interactive world. Milestones 4 (voice) and 5 (hardware) are
  **shelved, not deleted** — reservations about hardware integration, and the
  world track exercises the same character engine with a faster feedback loop.
  Both tracks share the Python core; the world is just a new `interfaces/`
  surface. Key feasibility conclusions live in the Milestone W section (no
  runtime image generation; LLM as brain / state machines as body; Streamlit
  ends at W3).

### Dev Environment:
- **June 2026 — Moved development to WSL2 (Ubuntu).** After Milestone 1 and the
  public/private split landed (a clean, no-half-finished-work moment), development
  moved off native Windows to WSL2.
  - **Why:** the recurring friction was entirely in *tooling*, not the app — e.g.
    the publish script needed Windows-specific fixes (read-only-bit `_rmtree`,
    `GIT_DIR` stripping, tar portability; see `scripts/publish_public_snapshot.py`),
    and running from a worktree needed a `PYTHONPATH=src` workaround. The codebase
    itself is pure Python with no platform-specific code, and future milestones are
    Linux-native (M4 voice via PyAudio/sounddevice, M5 Raspberry Pi hardware).
  - **How:** *fresh clone on the Linux filesystem* (`~/projects/...`), **never**
    `/mnt/c` (cross-boundary I/O is the main source of WSL pain). The gitignored
    local data — `.env`, `src/config/personality.private.json`, and `my-learnings/`
    — does not come with `git clone` and was carried over by hand. Editable install
    (`pip install -e ".[dev]"`) plus `pyproject.toml`'s `pythonpath = ["src"]` means
    the worktree `PYTHONPATH` workaround is no longer needed. VS Code connects via
    Remote-WSL; Claude Code runs inside WSL. The Windows checkout is kept temporarily
    as a fallback.

- **Milestone 2A (episodic memory):** The original M2 plan called for RAG/embeddings
  (2023-era recipe). Re-examined the plan before implementing: 1M context windows and
  Anthropic's first-class `memory_20250818` tool make that over-engineered for a personal
  project. Switched to agentic memory tool for semantic facts (2B). The `MemoryStore`
  Protocol mirrors the `Responder` Protocol from M1 — same pattern, backend-agnostic,
  testable with fakes. Code review caught a double `load_history` call in the CLI.
  Personality eval confirmed the model bump to sonnet-4-6 held the 0.96 baseline exactly.

### Interesting Discoveries:
- [Capture unexpected findings]

### Future Ideas:
- Multi-modal input (images of food/honey?)
- Emotion detection in voice
- Integration with smart home
- Mobile app
- Multi-language support

---

## Resources & References

### Learning Resources:
- [Anthropic Prompt Engineering Guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [LangChain Documentation](https://python.langchain.com/)
- [RAG Best Practices](https://docs.anthropic.com/en/docs/build-with-claude/rag)

### Technical References:
- Anthropic API Documentation
- OpenAI Whisper Documentation
- ChromaDB Documentation
- Raspberry Pi Documentation

### Inspiration:
- [Add any relevant projects or articles that inspire you]

---

**Last Updated:** July 6, 2026  
**Project Status:** Milestone 2 complete (memory system: episodic + durable facts, caching, consolidation, memory UI). New track opened: **Milestone W — Strohsack World** (multi-character cast, banter, pixel scenes, interactive world). Voice (M4) and hardware (M5) shelved.  
**Current Focus:** Sprint W1.1 — character abstraction (registry, per-character memory scoping, stub Bim Bam). Journey blog posts still pending.

---

*This is a living document. Update it as the project evolves, decisions change, and new insights emerge.*
