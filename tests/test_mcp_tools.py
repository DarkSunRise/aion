"""Tests for Aion MCP tools — memory and session tool wrappers."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from aion.memory.store import MemoryStore
from aion.memory.sessions import SessionDB
from aion.tools.mcp_tools import create_aion_tools
from aion.tools.server import create_aion_mcp_server


# ── Fixtures ──

@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(tmp_path / "memories", memory_char_limit=2000, user_char_limit=1000)
    store.load()
    return store


@pytest.fixture
def db(tmp_path):
    sdb = SessionDB(tmp_path / "test.db")
    sdb.connect()
    yield sdb
    sdb.close()


@pytest.fixture
def tools(memory, db):
    return create_aion_tools(memory, db)


def _get_tool(tools, name):
    """Find a tool's handler by name from the tools list."""
    for t in tools:
        if t.name == name:
            return t.handler
    raise KeyError(f"Tool '{name}' not found")


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _text_from(result):
    """Extract text content from a tool result dict."""
    assert "content" in result
    assert len(result["content"]) > 0
    return result["content"][0]["text"]


# ── Memory tools ──

class TestMemoryRead:
    def test_read_empty_memory(self, tools):
        tool = _get_tool(tools, "aion_memory_read")
        result = _run(tool({"target": "memory"}))
        assert "No memory memory entries" in _text_from(result)

    def test_read_empty_user(self, tools):
        tool = _get_tool(tools, "aion_memory_read")
        result = _run(tool({"target": "user"}))
        assert "No user memory entries" in _text_from(result)

    def test_read_populated_memory(self, memory, db):
        memory.add("memory", "Python 3.11 is installed")
        # Snapshot is frozen at load time — reload to capture new entries
        memory._snapshot["memory"] = memory._render("memory")
        tools = create_aion_tools(memory, db)
        tool = _get_tool(tools, "aion_memory_read")
        result = _run(tool({"target": "memory"}))
        assert "Python 3.11" in _text_from(result)

    def test_read_invalid_target(self, tools):
        tool = _get_tool(tools, "aion_memory_read")
        result = _run(tool({"target": "invalid"}))
        assert result.get("is_error") is True
        assert "must be" in _text_from(result)


class TestMemoryAdd:
    def test_add_entry(self, tools, memory):
        tool = _get_tool(tools, "aion_memory_add")
        result = _run(tool({"target": "memory", "content": "New fact"}))
        data = json.loads(_text_from(result))
        assert data["success"] is True
        assert "New fact" in memory.memory_entries

    def test_add_to_user(self, tools, memory):
        tool = _get_tool(tools, "aion_memory_add")
        result = _run(tool({"target": "user", "content": "Prefers dark mode"}))
        data = json.loads(_text_from(result))
        assert data["success"] is True
        assert "Prefers dark mode" in memory.user_entries

    def test_add_invalid_target(self, tools):
        tool = _get_tool(tools, "aion_memory_add")
        result = _run(tool({"target": "bad", "content": "test"}))
        assert result.get("is_error") is True


class TestMemoryReplace:
    def test_replace_entry(self, tools, memory):
        memory.add("memory", "Python 3.10 is installed")
        tool = _get_tool(tools, "aion_memory_replace")
        result = _run(tool({
            "target": "memory",
            "old_text": "Python 3.10",
            "content": "Python 3.11 is installed",
        }))
        data = json.loads(_text_from(result))
        assert data["success"] is True
        assert "3.11" in memory.memory_entries[0]

    def test_replace_no_match(self, tools, memory):
        memory.add("memory", "some fact")
        tool = _get_tool(tools, "aion_memory_replace")
        result = _run(tool({
            "target": "memory",
            "old_text": "nonexistent",
            "content": "replacement",
        }))
        data = json.loads(_text_from(result))
        assert data["success"] is False


class TestMemoryRemove:
    def test_remove_entry(self, tools, memory):
        memory.add("memory", "temporary note")
        tool = _get_tool(tools, "aion_memory_remove")
        result = _run(tool({"target": "memory", "old_text": "temporary"}))
        data = json.loads(_text_from(result))
        assert data["success"] is True
        assert len(memory.memory_entries) == 0

    def test_remove_no_match(self, tools, memory):
        tool = _get_tool(tools, "aion_memory_remove")
        result = _run(tool({"target": "memory", "old_text": "nonexistent"}))
        data = json.loads(_text_from(result))
        assert data["success"] is False


# ── Session tools ──

class TestSessionsList:
    def test_list_empty(self, tools):
        tool = _get_tool(tools, "aion_sessions_list")
        result = _run(tool({"limit": 10}))
        assert "No sessions" in _text_from(result)

    def test_list_with_sessions(self, tools, db):
        db.create_session("s1", source="cli", model="sonnet")
        db.add_message("s1", "user", "hello world")
        db.end_session("s1", title="Test session")

        tool = _get_tool(tools, "aion_sessions_list")
        result = _run(tool({"limit": 10}))
        text = _text_from(result)
        assert "s1" in text[:20] or "Test session" in text

    def test_list_respects_limit(self, tools, db):
        for i in range(5):
            db.create_session(f"s{i}", source="cli")
        tool = _get_tool(tools, "aion_sessions_list")
        result = _run(tool({"limit": 2}))
        # Should not contain all 5 sessions
        text = _text_from(result)
        assert text.count("\n") < 10  # reasonable limit


class TestSessionsSearch:
    def test_search_empty_query(self, tools):
        tool = _get_tool(tools, "aion_sessions_search")
        result = _run(tool({"query": "", "limit": 10}))
        assert result.get("is_error") is True

    def test_search_no_results(self, tools, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "hello world")
        tool = _get_tool(tools, "aion_sessions_search")
        result = _run(tool({"query": "nonexistent_xyzzy", "limit": 10}))
        assert "No results" in _text_from(result)

    def test_search_finds_match(self, tools, db):
        db.create_session("s1", source="cli")
        db.add_message("s1", "user", "deploying the gateway adapter")
        tool = _get_tool(tools, "aion_sessions_search")
        result = _run(tool({"query": "gateway", "limit": 10}))
        text = _text_from(result)
        assert "gateway" in text.lower()


class TestSessionMessages:
    def test_messages_not_found(self, tools):
        tool = _get_tool(tools, "aion_session_messages")
        result = _run(tool({"session_id": "nonexistent"}))
        assert result.get("is_error") is True
        assert "No session" in _text_from(result)

    def test_messages_empty_id(self, tools):
        tool = _get_tool(tools, "aion_session_messages")
        result = _run(tool({"session_id": ""}))
        assert result.get("is_error") is True

    def test_messages_full_conversation(self, tools, db):
        db.create_session("sess-abc-123", source="telegram")
        db.add_message("sess-abc-123", "user", "What is the weather?")
        db.add_message("sess-abc-123", "assistant", "It's sunny today.")

        tool = _get_tool(tools, "aion_session_messages")
        result = _run(tool({"session_id": "sess-abc-123"}))
        text = _text_from(result)
        assert "[USER]: What is the weather?" in text
        assert "[ASSISTANT]: It's sunny today." in text

    def test_messages_prefix_resolve(self, tools, db):
        db.create_session("abcdef12-3456-7890-abcd-ef1234567890", source="cli")
        db.add_message("abcdef12-3456-7890-abcd-ef1234567890", "user", "test message")

        tool = _get_tool(tools, "aion_session_messages")
        result = _run(tool({"session_id": "abcdef12"}))
        text = _text_from(result)
        assert "test message" in text


# ── Server factory ──

class TestMcpServer:
    def test_create_server_returns_config(self, memory, db):
        config = create_aion_mcp_server(memory, db)
        # McpSdkServerConfig is a TypedDict with type, name, instance
        assert config["type"] == "sdk"
        assert config["name"] == "aion"
        assert "instance" in config

    def test_tools_count(self, tools):
        assert len(tools) == 7
        names = {t.name for t in tools}
        assert names == {
            "aion_memory_read", "aion_memory_add",
            "aion_memory_replace", "aion_memory_remove",
            "aion_sessions_list", "aion_sessions_search",
            "aion_session_messages",
        }
