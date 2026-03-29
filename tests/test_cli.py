"""Tests for CLI argument parsing, session listing, and search formatting."""

import time

import pytest

from aion.cli import (
    _build_parser,
    _format_age,
    _format_cost,
    _print_sessions_table,
    _print_search_results,
)
from aion.memory.sessions import SessionDB


# ── Helpers ──

@pytest.fixture
def db(tmp_path):
    """Create a fresh SessionDB with sample data."""
    sdb = SessionDB(tmp_path / "test.db")
    sdb.connect()

    # Create sample sessions
    now = time.time()
    sdb.create_session("aaaa1111-0000-0000-0000-000000000000", source="cli", model="sonnet")
    sdb.end_session(
        "aaaa1111-0000-0000-0000-000000000000",
        cc_session_id="cc-1",
        cost_usd=0.03,
        title="fix auth module",
    )
    sdb.add_message("aaaa1111-0000-0000-0000-000000000000", "user", "fix the auth module")
    sdb.add_message("aaaa1111-0000-0000-0000-000000000000", "assistant", "Done fixing auth.")

    sdb.create_session("bbbb2222-0000-0000-0000-000000000000", source="tg", model="opus")
    sdb.end_session(
        "bbbb2222-0000-0000-0000-000000000000",
        cc_session_id="cc-2",
        cost_usd=0.12,
        title="add telegram adapter",
    )
    for i in range(5):
        sdb.add_message("bbbb2222-0000-0000-0000-000000000000", "user", f"msg {i}")

    yield sdb
    sdb.close()


# ── Format helpers ──

class TestFormatAge:
    def test_seconds(self):
        assert _format_age(time.time() - 30) == "30s"

    def test_minutes(self):
        assert _format_age(time.time() - 300) == "5m"

    def test_hours(self):
        assert _format_age(time.time() - 7200) == "2h"

    def test_days(self):
        assert _format_age(time.time() - 172800) == "2d"

    def test_none(self):
        assert _format_age(None) == "?"

    def test_zero(self):
        assert _format_age(0) == "?"


class TestFormatCost:
    def test_with_value(self):
        assert _format_cost(0.03) == "$0.03"

    def test_none(self):
        assert _format_cost(None) == "-"

    def test_zero(self):
        assert _format_cost(0.0) == "$0.00"


# ── Session table output ──

class TestSessionsTable:
    def test_table_header(self, capsys):
        sessions = [{
            "id": "aaaa1111-0000-0000-0000-000000000000",
            "title": "fix auth module",
            "source": "cli",
            "started_at": time.time() - 7200,
            "message_count": 12,
            "cost_usd": 0.03,
        }]
        _print_sessions_table(sessions)
        out = capsys.readouterr().out
        assert "ID" in out
        assert "TITLE" in out
        assert "SOURCE" in out
        assert "AGE" in out
        assert "MSGS" in out
        assert "COST" in out

    def test_table_row_content(self, capsys):
        sessions = [{
            "id": "aaaa1111-0000-0000-0000-000000000000",
            "title": "fix auth module",
            "source": "cli",
            "started_at": time.time() - 7200,
            "message_count": 12,
            "cost_usd": 0.03,
        }]
        _print_sessions_table(sessions)
        out = capsys.readouterr().out
        assert "aaaa.." in out
        assert "fix auth module" in out
        assert "cli" in out
        assert "$0.03" in out

    def test_table_empty(self, capsys):
        _print_sessions_table([])
        out = capsys.readouterr().out
        assert "No sessions found" in out

    def test_table_untitled(self, capsys):
        sessions = [{
            "id": "cccc3333-0000-0000-0000-000000000000",
            "title": None,
            "source": "cli",
            "started_at": time.time(),
            "message_count": 0,
            "cost_usd": None,
        }]
        _print_sessions_table(sessions)
        out = capsys.readouterr().out
        assert "(untitled)" in out
        assert "-" in out  # cost is None


# ── Search results output ──

class TestSearchResults:
    def test_empty(self, capsys):
        _print_search_results([])
        out = capsys.readouterr().out
        assert "No results found" in out

    def test_result_format(self, capsys):
        results = [{
            "session_id": "aaaa1111-0000-0000-0000-000000000000",
            "role": "user",
            "source": "cli",
            "snippet": "fix the >>>auth module<<< please",
            "title": "fix auth module",
            "started_at": time.time() - 3600,
        }]
        _print_search_results(results)
        out = capsys.readouterr().out
        assert "aaaa1111" in out
        assert "fix auth module" in out
        assert "user:" in out


# ── Argument parsing ──

class TestArgParsing:
    def test_resume_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--resume", "a3f2", "hello"])
        assert args.resume == "a3f2"
        assert args.prompt == "hello"

    def test_continue_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--continue"])
        assert args.continue_session is True

    def test_model_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--model", "claude-opus-4"])
        assert args.model == "claude-opus-4"

    def test_sessions_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--sessions"])
        assert args.sessions is True

    def test_search_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--search", "auth module"])
        assert args.search == "auth module"

    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.prompt is None
        assert args.model is None
        assert args.resume is None
        assert args.continue_session is False
        assert args.sessions is False
        assert args.search is None
        assert args.cwd == "."


# ── Integration: --sessions with real DB ──

class TestSessionsIntegration:
    def test_sessions_flag_outputs_table(self, db, capsys, tmp_path):
        """--sessions lists sessions from the DB."""
        # We can't easily call main() without mocking the whole config/agent chain,
        # so test the formatting with real DB data instead.
        sessions = db.recent_sessions(20)
        _print_sessions_table(sessions)
        out = capsys.readouterr().out
        assert "bbbb.." in out
        assert "aaaa.." in out
        assert "add telegram adapter" in out
        assert "fix auth module" in out

    def test_search_outputs_results(self, db, capsys):
        """Search returns formatted results from the DB."""
        results = db.search("auth", limit=10)
        _print_search_results(results)
        out = capsys.readouterr().out
        assert "auth" in out.lower()

    def test_resolve_prefix(self, db):
        """Prefix matching resolves to full session ID."""
        resolved = db.resolve_session_id("aaaa")
        assert resolved == "aaaa1111-0000-0000-0000-000000000000"

    def test_resolve_ambiguous(self, db):
        """Ambiguous prefix returns None."""
        # Both start with different prefixes, so a very short common prefix won't match
        # But "0000" appears in both IDs as part of the UUID
        # Create two sessions with same prefix
        db.create_session("xxxx0001-0000-0000-0000-000000000000", source="cli")
        db.create_session("xxxx0002-0000-0000-0000-000000000000", source="cli")
        resolved = db.resolve_session_id("xxxx")
        assert resolved is None

    def test_continue_gets_most_recent(self, db):
        """--continue should resolve to the most recent session."""
        recent = db.recent_sessions(1)
        assert len(recent) == 1
        # Most recent is the last created (bbbb)
        assert recent[0]["id"] == "bbbb2222-0000-0000-0000-000000000000"
