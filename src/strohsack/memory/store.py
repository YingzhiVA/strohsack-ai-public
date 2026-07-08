"""
Persistent storage for Strohsack's memory (Milestone 2A).

This is the *episodic* layer: it durably stores conversation history so a
session survives a restart — close the CLI, reopen it, and Strohsack picks up
where you left off. Storage is a local SQLite database; the file lives under a
gitignored ``data/`` directory and never leaves the machine (it holds real
conversation content, so it is private by construction and is never tracked or
published — see STROHSACK_PROJECT_PLAN.md, Pre-Public Hardening).

The :class:`MemoryStore` Protocol is the narrow surface that
:class:`~strohsack.conversation.manager.ConversationManager` depends on, mirroring
the ``Responder`` Protocol in that module: the manager stays backend-agnostic,
tests can pass a fake, and a richer backend (the agentic memory tool in 2B) can
slot in later. :class:`SQLiteMemoryStore` is the first concrete implementation
and additionally offers session management (create/resume/list/forget).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Default on-disk location, anchored to the project root (this file lives at
# ``<root>/src/strohsack/memory/store.py``) rather than the current working
# directory — so Strohsack's memory is the same file no matter where the CLI is
# launched from. ``data/`` is gitignored, so the database is never committed or
# included in the public snapshot. Override with the STROHSACK_DB_PATH env var.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "strohsack.db"

# v2 (M2C) adds the `facts` table for durable, cross-session facts Strohsack
# curates about the user via the remember() tool.
_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    label      TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

-- Durable facts (M2C). Cross-session: a fact outlives the session it was learned
-- in, so session_id is provenance only and survives session deletion (SET NULL).
CREATE TABLE IF NOT EXISTS facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fact       TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    """Resolve the database path from ``STROHSACK_DB_PATH`` or the default.

    Returns:
        The path to use for the SQLite database. The file need not exist yet;
        :class:`SQLiteMemoryStore` creates it (and its parent directory).
    """
    raw = os.getenv("STROHSACK_DB_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_DB_PATH


def _now() -> str:
    """Current UTC time as an ISO-8601 string (storage-friendly, sortable)."""
    return datetime.now(timezone.utc).isoformat()


class MemoryStore(Protocol):
    """Durable storage for a session's message history.

    The narrow contract :class:`~strohsack.conversation.manager.ConversationManager`
    depends on. :class:`SQLiteMemoryStore` satisfies it; tests can pass a stub.
    """

    def load_history(self, session_id: str) -> list[dict[str, str]]:
        """Return the stored messages for ``session_id`` (oldest first)."""
        ...

    def append_messages(self, session_id: str, messages: "Sequence[dict[str, str]]") -> None:
        """Append ``messages`` (``{"role", "content"}`` dicts) to ``session_id``."""
        ...


class SQLiteMemoryStore:
    """A SQLite-backed :class:`MemoryStore` with session management.

    A single store maps to one database file holding many sessions. Methods are
    guarded by a lock so the store is safe to share across threads (the Streamlit
    UI reuses one cached client/store across reruns).

    Args:
        db_path: Database file path. Defaults to :func:`default_db_path`. The
            parent directory is created if missing.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # check_same_thread=False so a single store can serve Streamlit's worker
        # threads; the lock serializes access, so it is used from one thread at a
        # time regardless.
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._apply_schema()

    def _apply_schema(self) -> None:
        """Create/reconcile tables and stamp the schema version.

        Called once during __init__ (already inside self._lock). The schema is
        written with ``CREATE TABLE IF NOT EXISTS``, so purely *additive*
        migrations (like v1 -> v2, which only added the ``facts`` table) are
        handled just by re-running the script. Non-additive steps (ALTER /
        backfill) must register in :meth:`_run_migrations`, which runs before the
        version stamp is advanced.
        """
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,)
            )
        elif row["version"] < _SCHEMA_VERSION:
            self._run_migrations(row["version"])
            self._conn.execute("UPDATE schema_version SET version = ?", (_SCHEMA_VERSION,))
        self._conn.commit()

    def _run_migrations(self, from_version: int) -> None:
        """Apply non-additive migration steps for versions above ``from_version``.

        Additive changes (new tables) are already covered by the ``CREATE TABLE
        IF NOT EXISTS`` script in :meth:`_apply_schema`, so v1 -> v2 needs no step
        here. Any *future* migration that needs an ALTER or a data backfill MUST
        register a callable keyed by the version it upgrades **to** — otherwise
        the version stamp would advance while the data change is silently skipped.
        """
        steps: dict[int, "Callable[[], None]"] = {
            # 3: self._migrate_v2_to_v3,  # example: register the next step here
        }
        for version in range(from_version + 1, _SCHEMA_VERSION + 1):
            step = steps.get(version)
            if step is not None:
                step()

    @property
    def path(self) -> Path:
        """The database file path backing this store."""
        return self._path

    def create_session(self, label: str | None = None) -> str:
        """Create a new, empty session and return its id.

        Args:
            label: Optional human-friendly name for the session.

        Returns:
            The new session's unique id.
        """
        session_id = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, created_at, updated_at, label) VALUES (?, ?, ?, ?)",
                (session_id, now, now, label),
            )
            self._conn.commit()
        return session_id

    def session_exists(self, session_id: str) -> bool:
        """Return whether a session with ``session_id`` exists."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def latest_session_id(self) -> str | None:
        """Return the most recently updated session's id, or ``None`` if empty.

        Used by the CLI to resume the previous conversation by default.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM sessions ORDER BY updated_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row is not None else None

    def load_history(self, session_id: str) -> list[dict[str, str]]:
        """Return ``session_id``'s messages as role/content dicts (oldest first)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def append_messages(self, session_id: str, messages: "Sequence[dict[str, str]]") -> None:
        """Append messages to a session and bump its ``updated_at``.

        Args:
            session_id: Target session (must already exist).
            messages: Ordered ``{"role", "content"}`` dicts to store.
        """
        if not messages:
            return
        now = _now()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                [(session_id, m["role"], m["content"], now) for m in messages],
            )
            self._conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()

    def list_sessions(self) -> list[dict[str, object]]:
        """Return all sessions (most recent first) with their message counts."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.created_at, s.updated_at, s.label, "
                "       COUNT(m.id) AS message_count "
                "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
                "GROUP BY s.id "
                "ORDER BY s.updated_at DESC, s.created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_session(self, session_id: str) -> None:
        """Delete all messages in a session, keeping the (now empty) session.

        Backs the CLI ``forget`` command: Strohsack forgets the conversation but
        the session row remains so it can be reused.
        """
        now = _now()
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()

    def add_fact(self, fact: str, session_id: str | None = None) -> bool:
        """Store a durable fact Strohsack learned about the user (M2C).

        Backs the ``remember()`` tool. Facts are cross-session; ``session_id``
        records where one was learned (provenance, and the unit the CLI
        ``forget`` command clears).

        Dedup is **per session** (not global): the same note isn't stored twice
        for one session, but two sessions may each keep their own copy. That keeps
        ``forget`` precise — clearing one session's facts can't delete a fact
        another session still relies on. :meth:`load_facts` collapses any
        cross-session duplicates for the prompt.

        Args:
            fact: The fact text. Empty/whitespace is ignored.
            session_id: The session in which the fact was learned, if known.

        Returns:
            True if the fact was stored, False if it was empty or a duplicate
            already held for this session.
        """
        text = fact.strip()
        if not text:
            return False
        now = _now()
        with self._lock:
            # NULL session_id needs `IS NULL` (``= NULL`` never matches in SQL).
            if session_id is None:
                existing = self._conn.execute(
                    "SELECT 1 FROM facts WHERE fact = ? AND session_id IS NULL", (text,)
                ).fetchone()
            else:
                existing = self._conn.execute(
                    "SELECT 1 FROM facts WHERE fact = ? AND session_id = ?",
                    (text, session_id),
                ).fetchone()
            if existing is not None:
                return False
            self._conn.execute(
                "INSERT INTO facts (fact, session_id, created_at) VALUES (?, ?, ?)",
                (text, session_id, now),
            )
            self._conn.commit()
        return True

    def load_facts(self) -> list[str]:
        """Return durable facts for prompt injection, oldest first, de-duplicated.

        Distinct fact *text* only (a fact learned in two sessions appears once),
        ordered by when it was first seen.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT fact FROM facts GROUP BY fact ORDER BY MIN(id)"
            ).fetchall()
        return [row["fact"] for row in rows]

    def list_facts(self) -> list[dict[str, object]]:
        """Return durable facts for the memory-management UI, oldest first.

        Like :meth:`load_facts` it collapses cross-session duplicates to one
        entry per distinct fact *text* (the unit a person thinks of as "a thing
        Strohsack knows"), but also returns the id of the fact's earliest copy
        so the UI has a stable per-fact key to render and delete by.

        Returns:
            One dict per distinct fact: ``{"id", "fact"}``, ordered by when the
            fact was first learned.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT MIN(id) AS id, fact FROM facts GROUP BY fact ORDER BY MIN(id)"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_fact(self, fact: str) -> int:
        """Delete a durable fact by its text, removing every copy (UI delete).

        Deletion is keyed on the fact *text*, not a single row id: a fact may be
        held under several sessions (see :meth:`add_fact`), and the person
        deleting it in the UI means "stop knowing this" — so all copies go, and
        it leaves the injected prompt entirely.

        Args:
            fact: The exact fact text to remove. Whitespace-trimmed to match how
                facts are stored.

        Returns:
            The number of rows deleted (0 if no fact matched).
        """
        text = fact.strip()
        if not text:
            return 0
        with self._lock:
            cursor = self._conn.execute("DELETE FROM facts WHERE fact = ?", (text,))
            self._conn.commit()
            return cursor.rowcount

    def clear_facts(self, session_id: str | None = None) -> None:
        """Delete durable facts.

        Args:
            session_id: When given, delete only facts learned in that session
                (the CLI ``forget`` semantics: forget this conversation). When
                ``None``, delete every fact (a full memory wipe).
        """
        with self._lock:
            if session_id is None:
                self._conn.execute("DELETE FROM facts")
            else:
                self._conn.execute("DELETE FROM facts WHERE session_id = ?", (session_id,))
            self._conn.commit()

    def replace_facts(self, facts: "Sequence[str]") -> None:
        """Swap the entire fact set for a consolidated one (M2C consolidation).

        Backs the ``consolidate`` flow: the model rewrites the fact list (merging
        near-duplicates, dropping stale notes), and we replace the table contents
        with the result. Consolidated facts are stored with ``session_id = NULL``
        — they're promoted to long-term memory and are no longer cleared by
        per-session ``forget`` (only a full wipe). Empty entries and exact
        duplicates are dropped.
        """
        cleaned: list[str] = []
        seen: set[str] = set()
        for fact in facts:
            text = fact.strip()
            if text and text not in seen:
                seen.add(text)
                cleaned.append(text)
        now = _now()
        with self._lock:
            self._conn.execute("DELETE FROM facts")
            self._conn.executemany(
                "INSERT INTO facts (fact, session_id, created_at) VALUES (?, NULL, ?)",
                [(text, now) for text in cleaned],
            )
            self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all of its messages (cascade)."""
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            self._conn.close()
