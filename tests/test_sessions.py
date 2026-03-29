"""Tests for SessionDB — thread safety, FTS5, migrations, rich listing, titles."""

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from aion.memory.sessions import SessionDB, SCHEMA_VERSION


@pytest.fixture
def db(tmp_path):
    """Create a fresh SessionDB for each test."""
    sdb = SessionDB(tmp_path / "test.db")
    sdb.connect()
    yield sdb
    sdb.close()


# ── Basic CRUD ──

class TestBasicCRUD:
    def test_create_and_get_session(self, db):
        db.create_session("s1", source="cli", model="sonnet")
        s = db.get_session("s1")
        assert s is not None
        assert s["source"] == "cli"
        assert s["model"] == "sonnet"
        assert s["message_count"] == 0

    def test_end_session(self, db):
        db.create_session("s1", source="cli")
        db.end_session("s1", cc_session_id="cc-123", cost_usd=0.05, end_reason="completed")
        s = db.get_session("s1")
        assert s["ended_at"] is not None
        assert s["cc_session_id"] == "cc-123"
        assert s["end_reason"] == "completed"

    def test_add_message_increments_count(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "hello")
        db.add_message("s1", "assistant", "hi there")
        s = db.get_session("s1")
        assert s["message_count"] == 2

    def test_add_message_with_tool_calls(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "assistant", "calling tool",
                        tool_calls=[{"name": "read_file", "args": {}}])
        s = db.get_session("s1")
        assert s["tool_call_count"] == 1

    def test_get_session_messages(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "hello")
        db.add_message("s1", "assistant", "world")
        msgs = db.get_session_messages("s1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "world"

    def test_parent_session(self, db):
        db.create_session("parent", source="cli")
        db.create_session("child", source="cli", parent_session_id="parent")
        child = db.get_session("child")
        assert child["parent_session_id"] == "parent"

    def test_get_cc_session_id(self, db):
        db.create_session("s1", source="cli")
        db.end_session("s1", cc_session_id="cc-abc")
        assert db.get_cc_session_id("s1") == "cc-abc"

    def test_recent_sessions(self, db):
        db.create_session("s1", source="cli")
        db.create_session("s2", source="telegram")
        sessions = db.recent_sessions(limit=10)
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0]["id"] == "s2"

    def test_session_count(self, db):
        assert db.session_count() == 0
        db.create_session("s1", source="cli")
        db.create_session("s2", source="telegram")
        assert db.session_count() == 2
        assert db.session_count(source="cli") == 1


# ── FTS5 Search ──

class TestFTS5Search:
    def test_basic_search(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "deploy the kubernetes cluster")
        db.add_message("s1", "assistant", "deploying now")
        results = db.search("kubernetes")
        assert len(results) >= 1
        assert results[0]["session_id"] == "s1"

    def test_search_returns_snippet(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "how to configure docker networking")
        results = db.search("docker")
        assert len(results) >= 1
        assert "snippet" in results[0]

    def test_search_empty_query(self, db):
        assert db.search("") == []
        assert db.search("   ") == []

    def test_search_messages_with_filters(self, db):
        db.create_session("s1", source="cli")
        db.create_session("s2", source="telegram")
        db.add_message("s1", "user", "python async await")
        db.add_message("s2", "user", "python decorators")
        results = db.search_messages("python", exclude_sources=["telegram"])
        assert all(r["source"] != "telegram" for r in results)

    def test_search_messages_role_filter(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "test query here")
        db.add_message("s1", "assistant", "test query response")
        results = db.search_messages("test query", role_filter=["user"])
        assert all(r["role"] == "user" for r in results)


# ── FTS5 Sanitization ──

class TestFTS5Sanitization:
    def test_special_chars_stripped(self):
        assert SessionDB._sanitize_fts5_query('hello + world') == 'hello   world'

    def test_quoted_phrases_preserved(self):
        result = SessionDB._sanitize_fts5_query('"exact phrase" other')
        assert '"exact phrase"' in result

    def test_unmatched_quotes_stripped(self):
        result = SessionDB._sanitize_fts5_query('hello "broken')
        assert '"' not in result or result.count('"') % 2 == 0

    def test_hyphenated_terms_quoted(self):
        result = SessionDB._sanitize_fts5_query('chat-send')
        assert '"chat-send"' in result

    def test_dangling_operators_removed(self):
        result = SessionDB._sanitize_fts5_query('AND hello')
        assert result == 'hello'

        result = SessionDB._sanitize_fts5_query('hello OR')
        assert result == 'hello'

    def test_leading_asterisk_removed(self):
        result = SessionDB._sanitize_fts5_query('* hello')
        assert result.strip() == 'hello'

    def test_prefix_wildcard_preserved(self):
        result = SessionDB._sanitize_fts5_query('deploy*')
        assert 'deploy*' in result

    def test_search_with_special_chars_no_crash(self, db):
        """Ensure special characters in search don't cause OperationalError."""
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "test content")
        # These should not raise
        db.search('hello "broken')
        db.search('(())++{}')
        db.search('AND OR NOT')
        db.search('')


# ── Thread Safety ──

class TestThreadSafety:
    def test_concurrent_writes(self, db):
        """Multiple threads writing simultaneously should not corrupt data."""
        db.create_session("s1", source="cli")
        errors = []
        num_threads = 10
        msgs_per_thread = 5

        def writer(thread_id):
            try:
                for i in range(msgs_per_thread):
                    db.add_message("s1", "user", f"thread-{thread_id}-msg-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent writes: {errors}"
        s = db.get_session("s1")
        assert s["message_count"] == num_threads * msgs_per_thread

    def test_concurrent_read_write(self, db):
        """Reads should not block writes and vice versa."""
        db.create_session("s1", source="cli")
        for i in range(20):
            db.add_message("s1", "user", f"message {i}")

        errors = []

        def reader():
            try:
                for _ in range(10):
                    db.get_session_messages("s1")
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(10):
                    db.add_message("s1", "assistant", f"response {i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ── Schema Migration ──

class TestSchemaMigration:
    def test_v1_to_v2_migration(self, tmp_path):
        """A v1 database should be migrated to v2 on open."""
        db_path = tmp_path / "migrate.db"

        # Create a v1 database manually
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (1);

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
        """)
        conn.execute(
            "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
            ("old-session", "cli", time.time()),
        )
        conn.commit()
        conn.close()

        # Open with SessionDB — should migrate
        sdb = SessionDB(db_path)
        sdb.connect()

        # Check version was updated
        row = sdb.conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == SCHEMA_VERSION

        # Check new columns exist
        s = sdb.get_session("old-session")
        assert "parent_session_id" in s
        assert "end_reason" in s
        assert "tool_call_count" in s
        assert "cache_read_tokens" in s

        # New columns should work
        sdb.create_session("new-session", source="cli", parent_session_id="old-session")
        ns = sdb.get_session("new-session")
        assert ns["parent_session_id"] == "old-session"

        sdb.close()


# ── Rich Listing ──

class TestRichListing:
    def test_list_sessions_rich(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "Hello, I need help with deployment")
        db.add_message("s1", "assistant", "Sure, let me help")

        sessions = db.list_sessions_rich()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s1"
        assert "preview" in sessions[0]
        assert "Hello" in sessions[0]["preview"]
        assert "last_active" in sessions[0]

    def test_list_sessions_rich_excludes_sources(self, db):
        db.create_session("s1", source="cli")
        db.create_session("s2", source="tool")
        sessions = db.list_sessions_rich(exclude_sources=["tool"])
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s1"

    def test_list_sessions_rich_source_filter(self, db):
        db.create_session("s1", source="cli")
        db.create_session("s2", source="telegram")
        sessions = db.list_sessions_rich(source="telegram")
        assert len(sessions) == 1
        assert sessions[0]["source"] == "telegram"


# ── Title Management ──

class TestTitleManagement:
    def test_set_and_get_title(self, db):
        db.create_session("s1", source="cli")
        assert db.set_session_title("s1", "My Session") is True
        s = db.get_session("s1")
        assert s["title"] == "My Session"

    def test_title_uniqueness(self, db):
        db.create_session("s1", source="cli")
        db.create_session("s2", source="cli")
        db.set_session_title("s1", "Unique Title")
        with pytest.raises(ValueError, match="already in use"):
            db.set_session_title("s2", "Unique Title")

    def test_title_sanitization(self):
        assert SessionDB.sanitize_title("  hello  world  ") == "hello world"
        assert SessionDB.sanitize_title("\x00bad\x1fchars") == "badchars"
        assert SessionDB.sanitize_title("") is None
        assert SessionDB.sanitize_title("   ") is None
        assert SessionDB.sanitize_title("\u200bhidden") == "hidden"

    def test_title_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            SessionDB.sanitize_title("x" * 200)

    def test_set_title_nonexistent_session(self, db):
        assert db.set_session_title("nonexistent", "Title") is False


# ── Session Resolution ──

class TestSessionResolution:
    def test_resolve_exact_id(self, db):
        db.create_session("abc-123-def", source="cli")
        assert db.resolve_session_id("abc-123-def") == "abc-123-def"

    def test_resolve_prefix(self, db):
        db.create_session("abc-123-def", source="cli")
        assert db.resolve_session_id("abc-123") == "abc-123-def"

    def test_resolve_ambiguous_prefix(self, db):
        db.create_session("abc-111", source="cli")
        db.create_session("abc-222", source="cli")
        assert db.resolve_session_id("abc") is None

    def test_resolve_no_match(self, db):
        assert db.resolve_session_id("nonexistent") is None


# ── Conversation Format ──

class TestConversationFormat:
    def test_get_messages_as_conversation(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "hello")
        db.add_message("s1", "assistant", "hi",
                        tool_calls=[{"name": "read_file", "args": {"path": "x"}}])
        db.add_message("s1", "tool", "file content",
                        tool_name="read_file", tool_call_id="tc-1")

        msgs = db.get_messages_as_conversation("s1")
        assert len(msgs) == 3
        assert msgs[0] == {"role": "user", "content": "hello"}
        assert "tool_calls" in msgs[1]
        assert msgs[2]["tool_name"] == "read_file"
        assert msgs[2]["tool_call_id"] == "tc-1"

    def test_reasoning_preserved_on_assistant(self, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "assistant", "result", reasoning="I thought about this")
        msgs = db.get_messages_as_conversation("s1")
        assert msgs[0]["reasoning"] == "I thought about this"


# ── WAL Checkpoint ──

class TestWALCheckpoint:
    def test_close_does_not_crash(self, tmp_path):
        """close() should work even if checkpoint fails."""
        sdb = SessionDB(tmp_path / "test.db")
        sdb.connect()
        sdb.create_session("s1", source="cli")
        sdb.close()
        # Should not raise
        sdb.close()  # Double close is safe
