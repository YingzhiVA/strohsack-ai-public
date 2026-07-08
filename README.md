# Strohsack AI 🐻🍯

**Bringing a Beloved Plush Bear to Life Through AI**

> An AI-powered conversational agent that embodies the unique personality of a beloved plush bear, Strohsack. From text-based chat toward a small explorable pixel world, this project chronicles the journey of building a complex, personality-driven AI application.

---

## 🎯 Project Vision

Strohsack is not just any chatbot—he's a lazy, honey-obsessed, mysteriously knowledgeable bear who claims to learn things in his dreams. Warm to everyone, he navigates the world with bear dignity, an encyclopaedic knowledge of honey, and a steadfast commitment to avoiding effort.

The current destination is **Strohsack World**: a cast of characters who banter with you *and* each other, pixel-art scenes that reflect the conversation, and eventually an interactive world you can poke (click a honey pot → Strohsack reacts). A voice-enabled body inside the plush bear himself remains a shelved-but-not-forgotten dream.

## ✨ Current Features

- 🎭 **Distinctive Personality** - Lazy, charming, honey-obsessed, with mysterious dream-learned knowledge
- 💬 **Text-based Chat** - Terminal (CLI) or browser (Streamlit) conversation with session context and streaming replies
- 🧠 **Persistent Memory** - Conversations survive restarts; CLI resumes your last session automatically (`--new` for a fresh start, `forget` to wipe)
- 🐝 **Durable Facts** - Strohsack curates lasting facts about you (your name, preferences, the people in your life) and recalls them across sessions. Facts are *injected* into context on read (free recall) and saved via a `remember()` tool on write; `tidy` has him consolidate his notes (merge duplicates, drop stale ones)
- 🧹 **Memory Management UI** - A 🧠 Memory page in the web app to see and prune what he remembers: view/delete individual facts, browse and delete past conversations, or fully wipe his memory — reading and writing the same store the CLI uses
- 🛡️ **Safety & Guardrails** - A never-store policy for memory (secrets, credentials, other people's private business... never written down — enforced by prompt *and* a deterministic guard) plus kid-safe conversational boundaries, all regression-tested by the personality eval. See the [safety guidelines](docs/architecture/safety.md)
- 🌍 **Strohsack World** - *(Next)* — a cast of characters, character-to-character banter, and pixel-art scenes driven by LLM scene directives
- 👥 **Guest Access & Sessions** - *(Planned)* — invitation-based, per-guest memory
- 🎤 **Voice Interface & Physical Integration** - *(Shelved — the world track comes first)*

For the full roadmap and current progress, see the **[Project Plan](STROHSACK_PROJECT_PLAN.md)**.

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/strohsack-ai.git
cd strohsack-ai

# Set up virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys

# Run the chatbot in your terminal
python -m strohsack.interfaces.cli

# ...or launch the web interface
streamlit run src/strohsack/interfaces/web.py
```

## 🏗️ Technical Stack

Python 3.10+ with the Claude API at its core. A Streamlit web UI, SQLite memory (episodic sessions + durable facts via inject-on-read / tool-on-write), an LLM-as-judge eval harness guarding personality and safety, and (next, for Strohsack World) FastAPI + WebSocket with a Phaser or Godot pixel stage. Full stack and rationale in the **[Project Plan](STROHSACK_PROJECT_PLAN.md#technical-stack-summary)**.

## 📚 Project Documentation

- **[Project Plan](STROHSACK_PROJECT_PLAN.md)** - Comprehensive roadmap and milestones
- **[Development Journey](docs/journey/)** - Blog-style posts documenting progress
- **[Architecture Docs](docs/architecture/)** - Technical decisions and system design

## 🎬 Demos

### Milestone 1 — Core Personality Chatbot

https://github.com/user-attachments/assets/e54d1da7-c3c9-4fcf-90df-fcfdf0ff702a

*Strohsack chatting via the Streamlit web interface, with streaming replies and session reset.*

## 🛣️ Roadmap

- [x] **Phase 0:** Foundation & Setup
- [x] **Milestone 1A:** Basic Chat Loop
- [x] **Milestone 1B:** Personality Eval
- [x] **Milestone 1C:** Web Interface
- [x] **Milestone 2A:** Episodic Memory (SQLite session persistence)
- [x] **Milestone 2B:** Agentic Memory Tool (durable facts via tool use)
- [x] **Milestone 2C:** Fast Memory (inject-on-read / tool-on-write), prompt caching, consolidation, memory UI
- [x] **Milestone 2.5:** Safety & Guardrails *(rescoped "2.5-lite": memory never-store policy + safety eval rubric)*
- [x] **Milestone 3.6:** Pre-Public Hardening *(public/private personality split, scripted snapshot publishing)*
- [~] **Milestone W:** Strohsack World *(Current — character cast → banter → pixel stage → interactive world)*
- [ ] **Milestone 3:** Access Control & Guest Sessions *(deferred; re-enters with the world's guest deploy)*
- [ ] **Milestone 3.5:** Analytics Dashboard *(optional)*
- [ ] **Milestone 4 & 5:** Voice Interface, Physical Integration *(shelved in favor of the world track)*

The detailed milestone breakdown, deliverables, and live status live in the **[Project Plan](STROHSACK_PROJECT_PLAN.md)**.

## 🧠 About Strohsack

Strohsack has a rich personality profile including:
- **Openness:** 95/100 - Highly curious and imaginative
- **Conscientiousness:** 15/100 - Proudly lazy and comfort-seeking
- **Extraversion:** 85/100 - Warm and gregarious
- **Agreeableness:** 75/100 - Straightforward and tender-minded
- **Neuroticism:** 20/100 - Emotionally stable

**Key Traits:**
- 🍯 Honey obsession: 100/100
- 😴 Nap enthusiasm: 90/100
- 🎓 Hidden knowledge depth: 90/100
- 🛋️ Laziness pride: 85/100

## 👨‍💻 Development Journey

This project serves dual purposes:
1. Creating a meaningful, personality-rich AI companion
2. Building a comprehensive portfolio showcasing AI application development

**Skills Demonstrated:**
- LLM integration and prompt engineering
- Agentic tool use and memory curation
- LLM-as-judge evaluation and eval-driven guardrails
- Safety engineering and privacy by design
- Multi-agent orchestration and real-time web *(upcoming — Strohsack World)*
- Software engineering best practices

## 🤝 Contributing

This is a personal portfolio project, but feedback and suggestions are welcome! Feel free to open an issue if you have ideas or spot any problems.

## 📝 License

*(To be determined)*

## 🙏 Acknowledgments

- Anthropic for Claude API
- The deeplearning.ai team for LLM education
- Strohsack himself for inspiring this project

---

**Project Status:** 🚧 Milestones 2 (Memory) and 2.5 (Safety & Guardrails) complete — next up: Milestone W, Strohsack World (character cast first)  
**Last Updated:** July 8, 2026

*"I learned it in my dreams, of course!" - Strohsack*
