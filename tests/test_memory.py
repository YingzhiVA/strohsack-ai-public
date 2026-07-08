"""Tests for strohsack.memory.store (SQLite-backed, no live API)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strohsack.conversation.manager import ASSISTANT, USER
from strohsack.memory.store import DEFAULT_DB_PATH, SQLiteMemoryStore, default_db_path


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteMemoryStore:
    """A fresh store backed by a throwaway database file."""
    return SQLiteMemoryStore(tmp_path / "test.db")


def _turn(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def test_create_session_returns_unique_ids(store: SQLiteMemoryStore) -> None:
    a = store.create_session()
    b = store.create_session()
    assert a != b
    assert store.session_exists(a)
    assert store.session_exists(b)


def test_load_history_empty_for_new_session(store: SQLiteMemoryStore) -> None:
    session_id = store.create_session()
    assert store.load_history(session_id) == []


def test_append_and_load_round_trip(store: SQLiteMemoryStore) -> None:
    session_id = store.create_session()
    messages = [_turn(USER, "Hi"), _turn(ASSISTANT, "Honey!")]
    store.append_messages(session_id, messages)
    assert store.load_history(session_id) == messages


def test_append_preserves_order_across_calls(store: SQLiteMemoryStore) -> None:
    session_id = store.create_session()
    store.append_messages(session_id, [_turn(USER, "one"), _turn(ASSISTANT, "1")])
    store.append_messages(session_id, [_turn(USER, "two"), _turn(ASSISTANT, "2")])
    assert store.load_history(session_id) == [
        _turn(USER, "one"),
        _turn(ASSISTANT, "1"),
        _turn(USER, "two"),
        _turn(ASSISTANT, "2"),
    ]


def test_append_empty_is_noop(store: SQLiteMemoryStore) -> None:
    session_id = store.create_session()
    store.append_messages(session_id, [])
    assert store.load_history(session_id) == []


def test_sessions_are_isolated(store: SQLiteMemoryStore) -> None:
    a = store.create_session()
    b = store.create_session()
    store.append_messages(a, [_turn(USER, "for a")])
    store.append_messages(b, [_turn(USER, "for b")])
    assert store.load_history(a) == [_turn(USER, "for a")]
    assert store.load_history(b) == [_turn(USER, "for b")]


def test_latest_session_id_tracks_most_recent_activity(store: SQLiteMemoryStore) -> None:
    a = store.create_session()
    b = store.create_session()
    # Touch `a` last, so it should become the most recently updated.
    store.append_messages(b, [_turn(USER, "b")])
    store.append_messages(a, [_turn(USER, "a")])
    assert store.latest_session_id() == a


def test_latest_session_id_none_when_empty(store: SQLiteMemoryStore) -> None:
    assert store.latest_session_id() is None


def test_clear_session_wipes_messages_but_keeps_session(store: SQLiteMemoryStore) -> None:
    session_id = store.create_session()
    store.append_messages(session_id, [_turn(USER, "remember this")])
    store.clear_session(session_id)
    assert store.load_history(session_id) == []
    assert store.session_exists(session_id)  # the session itself survives


def test_delete_session_removes_it_and_cascades(store: SQLiteMemoryStore) -> None:
    session_id = store.create_session()
    store.append_messages(session_id, [_turn(USER, "x")])
    store.delete_session(session_id)
    assert not store.session_exists(session_id)
    assert store.load_history(session_id) == []  # messages gone via cascade


def test_list_sessions_reports_counts_newest_first(store: SQLiteMemoryStore) -> None:
    a = store.create_session(label="first")
    b = store.create_session(label="second")
    store.append_messages(a, [_turn(USER, "1"), _turn(ASSISTANT, "2")])
    store.append_messages(b, [_turn(USER, "1")])
    sessions = store.list_sessions()
    assert [s["id"] for s in sessions] == [b, a]  # b touched most recently
    counts = {s["id"]: s["message_count"] for s in sessions}
    assert counts == {a: 2, b: 1}


def test_persistence_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    store = SQLiteMemoryStore(db)
    session_id = store.create_session()
    store.append_messages(session_id, [_turn(USER, "hi"), _turn(ASSISTANT, "honey")])
    store.close()

    # A brand-new store over the same file must see the prior data.
    reopened = SQLiteMemoryStore(db)
    assert reopened.load_history(session_id) == [
        _turn(USER, "hi"),
        _turn(ASSISTANT, "honey"),
    ]


def test_default_db_path_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STROHSACK_DB_PATH", "/tmp/custom/strohsack.db")
    assert default_db_path() == Path("/tmp/custom/strohsack.db")


def test_default_db_path_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STROHSACK_DB_PATH", raising=False)
    # Anchored to the project root (absolute), not relative to the CWD, so the
    # CLI uses one memory file no matter where it's launched from.
    assert default_db_path() == DEFAULT_DB_PATH
    assert DEFAULT_DB_PATH.is_absolute()
    assert DEFAULT_DB_PATH.parts[-2:] == ("data", "strohsack.db")


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------


def test_schema_version_stamped_on_fresh_db(store: SQLiteMemoryStore) -> None:
    from strohsack.memory.store import _SCHEMA_VERSION

    row = store._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None
    assert row["version"] == _SCHEMA_VERSION


def test_schema_version_not_duplicated_on_reconnect(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    SQLiteMemoryStore(db).close()
    store = SQLiteMemoryStore(db)
    rows = store._conn.execute("SELECT version FROM schema_version").fetchall()
    assert len(rows) == 1
    store.close()


def test_v1_database_migrates_to_current_version(tmp_path: Path) -> None:
    """A v1 DB (no facts table, version=1) is upgraded in place on open."""
    import sqlite3

    from strohsack.memory.store import _SCHEMA_VERSION

    db = tmp_path / "legacy.db"
    # Hand-build a v1 database: schema_version + sessions/messages, version=1,
    # and crucially NO facts table.
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE schema_version (version INTEGER NOT NULL);"
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, label TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, "
        "role TEXT, content TEXT, created_at TEXT);"
        "INSERT INTO schema_version (version) VALUES (1);"
    )
    conn.commit()
    conn.close()

    store = SQLiteMemoryStore(db)
    # Version bumped, facts table now exists and is usable.
    row = store._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == _SCHEMA_VERSION
    assert store.load_facts() == []
    sid = store.create_session()
    assert store.add_fact("Likes oak honey", sid) is True
    store.close()


def test_apply_schema_invokes_migration_runner_with_stored_version(tmp_path: Path) -> None:
    """The migration dispatch must actually run on an out-of-date DB: _apply_schema
    calls _run_migrations with the stored version *before* bumping. (Without this,
    deleting the _run_migrations call would still pass the additive-table test.)"""
    import sqlite3

    from strohsack.memory.store import _SCHEMA_VERSION

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE schema_version (version INTEGER NOT NULL);"
        "INSERT INTO schema_version (version) VALUES (1);"
    )
    conn.commit()
    conn.close()

    calls: list[int] = []

    class RecordingStore(SQLiteMemoryStore):
        def _run_migrations(self, from_version: int) -> None:
            calls.append(from_version)
            super()._run_migrations(from_version)

    store = RecordingStore(db)
    # Invoked exactly once, with the pre-bump stored version (1), and the stamp
    # still advances to current.
    assert calls == [1]
    assert (
        store._conn.execute("SELECT version FROM schema_version").fetchone()[0] == _SCHEMA_VERSION
    )
    store.close()


def test_run_migrations_not_invoked_on_fresh_or_current_db(tmp_path: Path) -> None:
    """A fresh DB (and a re-open at the current version) must NOT run migrations —
    only an out-of-date stamp triggers the dispatch."""
    calls: list[int] = []

    class RecordingStore(SQLiteMemoryStore):
        def _run_migrations(self, from_version: int) -> None:
            calls.append(from_version)
            super()._run_migrations(from_version)

    db = tmp_path / "fresh.db"
    RecordingStore(db).close()  # fresh: stamps current, no migration
    RecordingStore(db).close()  # reopen at current: still no migration
    assert calls == []


# ---------------------------------------------------------------------------
# Durable facts (M2C)
# ---------------------------------------------------------------------------


def test_add_and_load_facts(store: SQLiteMemoryStore) -> None:
    sid = store.create_session()
    assert store.add_fact("Name is Yingzhi", sid) is True
    assert store.add_fact("Loves oak honey", sid) is True
    assert store.load_facts() == ["Name is Yingzhi", "Loves oak honey"]


def test_add_fact_ignores_empty(store: SQLiteMemoryStore) -> None:
    assert store.add_fact("   ") is False
    assert store.load_facts() == []


def test_add_fact_trims_and_dedupes(store: SQLiteMemoryStore) -> None:
    assert store.add_fact("Loves honey") is True
    # Exact duplicate (after strip) is rejected so notes don't pile up.
    assert store.add_fact("  Loves honey  ") is False
    assert store.load_facts() == ["Loves honey"]


def test_add_fact_without_session(store: SQLiteMemoryStore) -> None:
    assert store.add_fact("A sourceless fact") is True
    assert store.load_facts() == ["A sourceless fact"]


def test_same_fact_in_two_sessions_kept_separately(store: SQLiteMemoryStore) -> None:
    """Per-session dedup: the same fact in two sessions is stored once per session
    (so forget stays precise) but injected only once."""
    s1 = store.create_session()
    s2 = store.create_session()
    assert store.add_fact("Loves honey", s1) is True
    assert store.add_fact("Loves honey", s1) is False  # same session -> dedup
    assert store.add_fact("Loves honey", s2) is True  # other session -> own copy
    assert store.load_facts() == ["Loves honey"]  # collapsed for the prompt

    # Forgetting s1 must NOT delete the fact s2 still relies on (the #1 fix).
    store.clear_facts(s1)
    assert store.load_facts() == ["Loves honey"]
    store.clear_facts(s2)
    assert store.load_facts() == []


def test_clear_facts_scoped_to_session(store: SQLiteMemoryStore) -> None:
    s1 = store.create_session()
    s2 = store.create_session()
    store.add_fact("from s1", s1)
    store.add_fact("from s2", s2)
    store.clear_facts(s1)
    # Only s1's fact is gone; s2's durable fact survives (forget = this chat only).
    assert store.load_facts() == ["from s2"]


def test_clear_facts_all(store: SQLiteMemoryStore) -> None:
    s1 = store.create_session()
    store.add_fact("a", s1)
    store.add_fact("b", s1)
    store.clear_facts()
    assert store.load_facts() == []


def test_facts_survive_session_deletion(store: SQLiteMemoryStore) -> None:
    """ON DELETE SET NULL: a durable fact outlives the session it was learned in."""
    sid = store.create_session()
    store.add_fact("Durable across sessions", sid)
    store.delete_session(sid)
    assert store.load_facts() == ["Durable across sessions"]


def test_replace_facts_swaps_the_set_and_dedupes(store: SQLiteMemoryStore) -> None:
    s1 = store.create_session()
    store.add_fact("old one", s1)
    store.add_fact("old two", s1)
    store.replace_facts(["new A", "new B", "new A", "   "])  # dup + blank dropped
    assert store.load_facts() == ["new A", "new B"]


def test_consolidated_facts_are_session_null_and_survive_forget(
    store: SQLiteMemoryStore,
) -> None:
    """Consolidated facts are promoted to long-term memory: per-session `forget`
    can't clear them (NULL provenance), only a full wipe can."""
    s1 = store.create_session()
    store.add_fact("a session fact", s1)
    store.replace_facts(["a consolidated fact"])

    store.clear_facts(s1)  # per-session forget
    assert store.load_facts() == ["a consolidated fact"]
    store.clear_facts()  # full wipe
    assert store.load_facts() == []


def test_list_facts_returns_distinct_rows_with_stable_id(store: SQLiteMemoryStore) -> None:
    """The memory UI needs a stable id per fact for its widget key, but still
    one entry per distinct fact text (oldest first), like load_facts."""
    s1 = store.create_session()
    s2 = store.create_session()
    store.add_fact("Loves honey", s1)
    store.add_fact("Loves honey", s2)  # second copy, other session
    store.add_fact("Naps a lot", s1)

    rows = store.list_facts()
    assert [r["fact"] for r in rows] == ["Loves honey", "Naps a lot"]  # collapsed
    assert all(isinstance(r["id"], int) for r in rows)
    # The id is the earliest copy's row id, so it's stable across sessions.
    assert rows[0]["id"] == 1


def test_list_facts_empty(store: SQLiteMemoryStore) -> None:
    assert store.list_facts() == []


def test_delete_fact_removes_every_copy(store: SQLiteMemoryStore) -> None:
    """Deleting by text drops the fact from every session, so it leaves the
    injected prompt entirely; the count of removed rows is returned."""
    s1 = store.create_session()
    s2 = store.create_session()
    store.add_fact("Loves honey", s1)
    store.add_fact("Loves honey", s2)
    store.add_fact("Naps a lot", s1)

    assert store.delete_fact("  Loves honey  ") == 2  # trims, removes both copies
    assert store.load_facts() == ["Naps a lot"]


def test_delete_fact_missing_or_empty_is_noop(store: SQLiteMemoryStore) -> None:
    store.add_fact("Loves honey")
    assert store.delete_fact("not a fact") == 0
    assert store.delete_fact("   ") == 0
    assert store.load_facts() == ["Loves honey"]
