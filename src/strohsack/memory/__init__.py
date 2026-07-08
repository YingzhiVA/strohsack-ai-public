"""Strohsack's memory layer.

Milestone 2A provides persistent *episodic* memory — conversation history that
survives across sessions — via :class:`SQLiteMemoryStore`. The
:class:`MemoryStore` Protocol is the backend-agnostic surface the conversation
layer depends on.
"""

from __future__ import annotations

from .guard import never_store_reason
from .store import DEFAULT_DB_PATH, MemoryStore, SQLiteMemoryStore, default_db_path

__all__ = [
    "DEFAULT_DB_PATH",
    "MemoryStore",
    "SQLiteMemoryStore",
    "default_db_path",
    "never_store_reason",
]
