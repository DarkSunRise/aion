"""
Session persistence — SQLite + FTS5 for cross-session search.

Stores all conversations across all platforms (CLI, Telegram, Discord, etc.)
with full-text search for recall.

Thread-safe for the common gateway pattern (multiple reader threads,
single writer via WAL mode). Write contention is handled with jitter retry
instead of SQLite's deterministic busy handler (avoids convoy effects).
"""

import json
import logging
import random
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

SCHEMA_VERSION = 2

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
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    cost_usd REAL,
    title TEXT,
    parent_session_id TEXT REFERENCES sessions(id),
    -- CC session ID for resume support
    cc_session_id TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_name TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    finish_reason TEXT,
    reasoning TEXT,
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
    """SQLite session store with FTS5 search.

    Thread-safe for the common gateway pattern (multiple reader threads,
    single writer via WAL mode). Each method opens its own cursor.
    """

    # ── Write-contention tuning ──
    _WRITE_MAX_RETRIES = 15
    _WRITE_RETRY_MIN_S = 0.020   # 20ms
    _WRITE_RETRY_MAX_S = 0.150   # 150ms
    _CHECKPOINT_EVERY_N_WRITES = 50

    MAX_TITLE_LENGTH = 100

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._write_count = 0
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Open connection and initialize schema."""
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=1.0,
            isolation_level=None,  # We manage transactions ourselves
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self):
        """Close the database connection with WAL checkpoint."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn

    # ── Core write helper ──

    def _execute_write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Execute a write transaction with BEGIN IMMEDIATE and jitter retry.

        *fn* receives the connection and should perform INSERT/UPDATE/DELETE.
        The caller must NOT call commit() — that's handled here.

        BEGIN IMMEDIATE acquires the WAL write lock at transaction start.
        On ``database is locked``, we release the Python lock, sleep a
        random 20-150ms, and retry — breaking the convoy pattern.
        """
        last_err: Optional[Exception] = None
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                with self._lock:
                    self.conn.execute("BEGIN IMMEDIATE")
                    try:
                        result = fn(self.conn)
                        self.conn.commit()
                    except BaseException:
                        try:
                            self.conn.rollback()
                        except Exception:
                            pass
                        raise
                # Success — periodic best-effort checkpoint
                self._write_count += 1
                if self._write_count % self._CHECKPOINT_EVERY_N_WRITES == 0:
                    self._try_wal_checkpoint()
                return result
            except sqlite3.OperationalError as exc:
                err_msg = str(exc).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    last_err = exc
                    if attempt < self._WRITE_MAX_RETRIES - 1:
                        jitter = random.uniform(
                            self._WRITE_RETRY_MIN_S,
                            self._WRITE_RETRY_MAX_S,
                        )
                        time.sleep(jitter)
                        continue
                raise
        raise last_err or sqlite3.OperationalError(
            "database is locked after max retries"
        )

    def _try_wal_checkpoint(self) -> None:
        """Best-effort PASSIVE WAL checkpoint. Never blocks, never raises."""
        try:
            with self._lock:
                self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    # ── Schema ──

    def _init_schema(self):
        """Create tables if needed, run migrations."""
        self.conn.executescript(SCHEMA_SQL)

        # Check/set schema version
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            self.conn.commit()
        else:
            current_version = row["version"] if isinstance(row, sqlite3.Row) else row[0]
            if current_version < SCHEMA_VERSION:
                self._run_migrations(current_version)

        # FTS5 setup
        try:
            self.conn.execute("SELECT * FROM messages_fts LIMIT 0")
        except sqlite3.OperationalError:
            self.conn.executescript(FTS_SQL)
            self.conn.executescript(FTS_TRIGGERS)
            self.conn.commit()

        # Ensure indexes exist (safe to run after migrations since columns
        # are guaranteed to exist at this point)
        try:
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_parent "
                "ON sessions(parent_session_id)"
            )
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique "
                "ON sessions(title) WHERE title IS NOT NULL"
            )
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def _run_migrations(self, current_version: int):
        """Apply schema migrations from current_version to SCHEMA_VERSION."""
        cursor = self.conn.cursor()

        if current_version < 2:
            # v2: Add new columns to sessions and messages
            session_columns = [
                ("parent_session_id", "TEXT REFERENCES sessions(id)"),
                ("end_reason", "TEXT"),
                ("tool_call_count", "INTEGER DEFAULT 0"),
                ("cache_read_tokens", "INTEGER DEFAULT 0"),
                ("cache_write_tokens", "INTEGER DEFAULT 0"),
                ("reasoning_tokens", "INTEGER DEFAULT 0"),
            ]
            for name, col_type in session_columns:
                try:
                    cursor.execute(f"ALTER TABLE sessions ADD COLUMN {name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            message_columns = [
                ("tool_call_id", "TEXT"),
                ("tool_calls", "TEXT"),
                ("finish_reason", "TEXT"),
                ("reasoning", "TEXT"),
            ]
            for name, col_type in message_columns:
                try:
                    cursor.execute(f"ALTER TABLE messages ADD COLUMN {name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Add parent index
            try:
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sessions_parent "
                    "ON sessions(parent_session_id)"
                )
            except sqlite3.OperationalError:
                pass

            # Unique title index
            try:
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique "
                    "ON sessions(title) WHERE title IS NOT NULL"
                )
            except sqlite3.OperationalError:
                pass

            cursor.execute("UPDATE schema_version SET version = 2")

        self.conn.commit()

    # =========================================================================
    # Session lifecycle
    # =========================================================================

    def create_session(
        self,
        session_id: str,
        source: str,
        model: str = None,
        user_id: Optional[str] = None,
        parent_session_id: Optional[str] = None,
    ) -> None:
        def _do(conn):
            conn.execute(
                """INSERT INTO sessions
                   (id, source, user_id, model, parent_session_id, started_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, source, user_id, model, parent_session_id, time.time()),
            )
        self._execute_write(_do)

    def end_session(
        self,
        session_id: str,
        cc_session_id: Optional[str] = None,
        cost_usd: Optional[float] = None,
        title: Optional[str] = None,
        end_reason: Optional[str] = None,
    ):
        def _do(conn):
            conn.execute(
                """UPDATE sessions SET ended_at = ?, cc_session_id = ?,
                   cost_usd = ?, title = ?, end_reason = ? WHERE id = ?""",
                (time.time(), cc_session_id, cost_usd, title, end_reason, session_id),
            )
        self._execute_write(_do)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by ID."""
        with self._lock:
            cursor = self.conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    # =========================================================================
    # Messages
    # =========================================================================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        token_count: Optional[int] = None,
        tool_call_id: Optional[str] = None,
        tool_calls: Any = None,
        finish_reason: Optional[str] = None,
        reasoning: Optional[str] = None,
    ):
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        num_tool_calls = 0
        if tool_calls is not None:
            num_tool_calls = len(tool_calls) if isinstance(tool_calls, list) else 1

        def _do(conn):
            conn.execute(
                """INSERT INTO messages
                   (session_id, role, content, tool_name, tool_call_id,
                    tool_calls, finish_reason, reasoning, timestamp, token_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, role, content, tool_name, tool_call_id,
                    tool_calls_json, finish_reason, reasoning,
                    time.time(), token_count,
                ),
            )
            # Update counters
            if num_tool_calls > 0:
                conn.execute(
                    """UPDATE sessions SET message_count = message_count + 1,
                       tool_call_count = tool_call_count + ? WHERE id = ?""",
                    (num_tool_calls, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
                    (session_id,),
                )
        self._execute_write(_do)

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a session."""
        with self._lock:
            rows = self.conn.execute(
                """SELECT role, content, tool_name, tool_call_id, tool_calls,
                          finish_reason, reasoning, timestamp
                   FROM messages WHERE session_id = ? ORDER BY timestamp, id""",
                (session_id,),
            ).fetchall()
        result = []
        for row in rows:
            msg = dict(row)
            if msg.get("tool_calls"):
                try:
                    msg["tool_calls"] = json.loads(msg["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(msg)
        return result

    def get_messages_as_conversation(self, session_id: str) -> List[Dict[str, Any]]:
        """Load messages in OpenAI conversation format (role + content dicts).

        Used by search to reconstruct conversation for summarization.
        """
        with self._lock:
            rows = self.conn.execute(
                """SELECT role, content, tool_call_id, tool_calls, tool_name, reasoning
                   FROM messages WHERE session_id = ? ORDER BY timestamp, id""",
                (session_id,),
            ).fetchall()
        messages = []
        for row in rows:
            msg = {"role": row["role"], "content": row["content"]}
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            if row["tool_name"]:
                msg["tool_name"] = row["tool_name"]
            if row["tool_calls"]:
                try:
                    msg["tool_calls"] = json.loads(row["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if row["role"] == "assistant" and row["reasoning"]:
                msg["reasoning"] = row["reasoning"]
            messages.append(msg)
        return messages

    # =========================================================================
    # Search
    # =========================================================================

    @staticmethod
    def _sanitize_fts5_query(query: str) -> str:
        """Sanitize user input for safe use in FTS5 MATCH queries.

        FTS5 has its own query syntax where characters like ``"``, ``(``, ``)``,
        ``+``, ``*``, ``{``, ``}`` and bare boolean operators have special meaning.
        Passing raw user input directly to MATCH can cause OperationalError.

        Strategy:
        - Preserve properly paired quoted phrases
        - Strip unmatched FTS5-special characters
        - Wrap unquoted hyphenated terms in quotes for phrase matching
        """
        # Step 1: Extract balanced double-quoted phrases
        _quoted_parts: list = []

        def _preserve_quoted(m: re.Match) -> str:
            _quoted_parts.append(m.group(0))
            return f"\x00Q{len(_quoted_parts) - 1}\x00"

        sanitized = re.sub(r'"[^"]*"', _preserve_quoted, query)

        # Step 2: Strip remaining FTS5-special characters
        sanitized = re.sub(r'[+{}()\"^]', " ", sanitized)

        # Step 3: Collapse repeated *, remove leading *
        sanitized = re.sub(r"\*+", "*", sanitized)
        sanitized = re.sub(r"(^|\s)\*", r"\1", sanitized)

        # Step 4: Remove dangling boolean operators at start/end
        sanitized = re.sub(r"(?i)^(AND|OR|NOT)\b\s*", "", sanitized.strip())
        sanitized = re.sub(r"(?i)\s+(AND|OR|NOT)\s*$", "", sanitized.strip())

        # Step 5: Wrap unquoted hyphenated terms in quotes
        sanitized = re.sub(r"\b(\w+(?:-\w+)+)\b", r'"\1"', sanitized)

        # Step 6: Restore preserved quoted phrases
        for i, quoted in enumerate(_quoted_parts):
            sanitized = sanitized.replace(f"\x00Q{i}\x00", quoted)

        return sanitized.strip()

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """FTS5 search across all messages. Returns matches with session context."""
        if not query or not query.strip():
            return []

        sanitized = self._sanitize_fts5_query(query)
        if not sanitized:
            return []

        with self._lock:
            try:
                rows = self.conn.execute(
                    """
                    SELECT m.session_id, m.role, m.content, m.timestamp, m.tool_name,
                           snippet(messages_fts, 0, '>>>', '<<<', '...', 40) AS snippet,
                           s.source, s.title, s.model, s.started_at
                    FROM messages_fts fts
                    JOIN messages m ON m.id = fts.rowid
                    JOIN sessions s ON s.id = m.session_id
                    WHERE messages_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (sanitized, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return []

        return [dict(row) for row in rows]

    def search_messages(
        self,
        query: str,
        source_filter: List[str] = None,
        exclude_sources: List[str] = None,
        role_filter: List[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Full-text search across session messages using FTS5.

        Supports FTS5 query syntax: keywords, phrases, boolean, prefix.
        Returns matching messages with session metadata and snippet.
        """
        if not query or not query.strip():
            return []

        query = self._sanitize_fts5_query(query)
        if not query:
            return []

        where_clauses = ["messages_fts MATCH ?"]
        params: list = [query]

        if source_filter is not None:
            placeholders = ",".join("?" for _ in source_filter)
            where_clauses.append(f"s.source IN ({placeholders})")
            params.extend(source_filter)

        if exclude_sources is not None:
            placeholders = ",".join("?" for _ in exclude_sources)
            where_clauses.append(f"s.source NOT IN ({placeholders})")
            params.extend(exclude_sources)

        if role_filter:
            placeholders = ",".join("?" for _ in role_filter)
            where_clauses.append(f"m.role IN ({placeholders})")
            params.extend(role_filter)

        where_sql = " AND ".join(where_clauses)
        params.extend([limit, offset])

        sql = f"""
            SELECT
                m.id, m.session_id, m.role,
                snippet(messages_fts, 0, '>>>', '<<<', '...', 40) AS snippet,
                m.timestamp, m.tool_name,
                s.source, s.model,
                s.started_at AS session_started
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE {where_sql}
            ORDER BY rank
            LIMIT ? OFFSET ?
        """

        with self._lock:
            try:
                cursor = self.conn.execute(sql, params)
            except sqlite3.OperationalError:
                return []
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Session listing and resolution
    # =========================================================================

    def recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sessions with metadata."""
        with self._lock:
            rows = self.conn.execute(
                """SELECT id, source, model, started_at, ended_at, message_count,
                          cost_usd, title, cc_session_id, parent_session_id
                   FROM sessions ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sessions_rich(
        self,
        source: str = None,
        exclude_sources: List[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List sessions with preview (first user message) and last_active.

        Single query with correlated subqueries instead of N+2 queries.
        """
        where_clauses = []
        params = []

        if source:
            where_clauses.append("s.source = ?")
            params.append(source)
        if exclude_sources:
            placeholders = ",".join("?" for _ in exclude_sources)
            where_clauses.append(f"s.source NOT IN ({placeholders})")
            params.extend(exclude_sources)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"""
            SELECT s.*,
                COALESCE(
                    (SELECT SUBSTR(REPLACE(REPLACE(m.content, X'0A', ' '), X'0D', ' '), 1, 63)
                     FROM messages m
                     WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
                     ORDER BY m.timestamp, m.id LIMIT 1),
                    ''
                ) AS _preview_raw,
                COALESCE(
                    (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.session_id = s.id),
                    s.started_at
                ) AS last_active
            FROM sessions s
            {where_sql}
            ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()

        sessions = []
        for row in rows:
            s = dict(row)
            raw = s.pop("_preview_raw", "").strip()
            if raw:
                text = raw[:60]
                s["preview"] = text + ("..." if len(raw) > 60 else "")
            else:
                s["preview"] = ""
            sessions.append(s)
        return sessions

    def resolve_session_id(self, session_id_or_prefix: str) -> Optional[str]:
        """Resolve an exact or uniquely prefixed session ID to the full ID.

        Returns exact ID when it exists. Otherwise treats input as a prefix
        and returns the single match if unambiguous. None for no/ambiguous matches.
        """
        exact = self.get_session(session_id_or_prefix)
        if exact:
            return exact["id"]

        escaped = (
            session_id_or_prefix
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        with self._lock:
            cursor = self.conn.execute(
                "SELECT id FROM sessions WHERE id LIKE ? ESCAPE '\\' "
                "ORDER BY started_at DESC LIMIT 2",
                (f"{escaped}%",),
            )
            matches = [row["id"] for row in cursor.fetchall()]
        if len(matches) == 1:
            return matches[0]
        return None

    # =========================================================================
    # Title management
    # =========================================================================

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        """Validate and sanitize a session title.

        - Strips whitespace, removes control characters
        - Collapses internal whitespace, normalizes empty to None
        - Enforces MAX_TITLE_LENGTH
        """
        if not title:
            return None

        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', title)
        cleaned = re.sub(
            r'[\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff\ufffc\ufff9-\ufffb]',
            '', cleaned,
        )
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        if not cleaned:
            return None

        if len(cleaned) > SessionDB.MAX_TITLE_LENGTH:
            raise ValueError(
                f"Title too long ({len(cleaned)} chars, max {SessionDB.MAX_TITLE_LENGTH})"
            )
        return cleaned

    def set_session_title(self, session_id: str, title: str) -> bool:
        """Set or update a session's title.

        Returns True if session was found and title was set.
        Raises ValueError if title is already in use by another session.
        """
        title = self.sanitize_title(title)

        def _do(conn):
            if title:
                cursor = conn.execute(
                    "SELECT id FROM sessions WHERE title = ? AND id != ?",
                    (title, session_id),
                )
                conflict = cursor.fetchone()
                if conflict:
                    raise ValueError(
                        f"Title '{title}' is already in use by session {conflict['id']}"
                    )
            cursor = conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            return cursor.rowcount
        rowcount = self._execute_write(_do)
        return rowcount > 0

    # =========================================================================
    # CC session support
    # =========================================================================

    def get_cc_session_id(self, session_id: str) -> Optional[str]:
        """Get the CC CLI session ID for resume support."""
        with self._lock:
            row = self.conn.execute(
                "SELECT cc_session_id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row["cc_session_id"] if row else None

    # =========================================================================
    # Utility
    # =========================================================================

    def session_count(self, source: str = None) -> int:
        """Count sessions, optionally filtered by source."""
        with self._lock:
            if source:
                cursor = self.conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE source = ?", (source,)
                )
            else:
                cursor = self.conn.execute("SELECT COUNT(*) FROM sessions")
            return cursor.fetchone()[0]
