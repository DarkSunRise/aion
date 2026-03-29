"""
Session persistence — SQLite + FTS5 for cross-session search.

Stores all conversations across all platforms (CLI, Telegram, Discord, etc.)
with full-text search for recall.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    message_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL,
    title TEXT,
    -- CC session ID for resume support
    cc_session_id TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=id
);
"""

FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES (new.id, new.content);
END;
"""


class SessionDB:
    """SQLite session store with FTS5 search."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Open connection and initialize schema."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn

    def _init_schema(self):
        """Create tables if needed."""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.executescript(FTS_SQL)
        self.conn.executescript(FTS_TRIGGERS)

        # Check/set schema version
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        self.conn.commit()

    # --- Session CRUD ---

    def create_session(self, session_id: str, source: str, model: str,
                       user_id: Optional[str] = None) -> None:
        self.conn.execute(
            "INSERT INTO sessions (id, source, user_id, model, started_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, source, user_id, model, time.time()),
        )
        self.conn.commit()

    def end_session(self, session_id: str, cc_session_id: Optional[str] = None,
                    cost_usd: Optional[float] = None, title: Optional[str] = None):
        self.conn.execute(
            """UPDATE sessions SET ended_at = ?, cc_session_id = ?,
               cost_usd = ?, title = ? WHERE id = ?""",
            (time.time(), cc_session_id, cost_usd, title, session_id),
        )
        self.conn.commit()

    def add_message(self, session_id: str, role: str, content: str,
                    tool_name: Optional[str] = None, token_count: Optional[int] = None):
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_name, timestamp, token_count) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, tool_name, time.time(), token_count),
        )
        self.conn.execute(
            "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
            (session_id,),
        )
        self.conn.commit()

    # --- Search ---

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """FTS5 search across all messages. Returns matches with session context."""
        rows = self.conn.execute(
            """
            SELECT m.session_id, m.role, m.content, m.timestamp, m.tool_name,
                   s.source, s.title, s.model, s.started_at
            FROM messages_fts fts
            JOIN messages m ON m.id = fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()

        return [dict(row) for row in rows]

    def recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sessions with metadata."""
        rows = self.conn.execute(
            """SELECT id, source, model, started_at, ended_at, message_count,
                      cost_usd, title, cc_session_id
               FROM sessions ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a session."""
        rows = self.conn.execute(
            "SELECT role, content, tool_name, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_cc_session_id(self, session_id: str) -> Optional[str]:
        """Get the CC CLI session ID for resume support."""
        row = self.conn.execute(
            "SELECT cc_session_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row["cc_session_id"] if row else None
