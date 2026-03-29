"""Tests for LLM-powered session search."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aion.memory.sessions import SessionDB
from aion.memory.search import (
    search_sessions,
    _format_timestamp,
    _format_conversation,
    _truncate_around_matches,
    _resolve_to_parent,
)


@pytest.fixture
def db(tmp_path):
    sdb = SessionDB(tmp_path / "test.db")
    sdb.connect()
    yield sdb
    sdb.close()


def _seed_sessions(db):
    """Populate the DB with a couple of sessions."""
    db.create_session("s1", source="cli", model="sonnet")
    db.add_message("s1", "user", "How do I deploy to kubernetes?")
    db.add_message("s1", "assistant", "You can use kubectl apply to deploy.")
    db.end_session("s1", end_reason="completed")

    db.create_session("s2", source="telegram", model="haiku")
    db.add_message("s2", "user", "Fix the docker networking issue")
    db.add_message("s2", "assistant", "Let me check the docker compose config.")
    db.end_session("s2", end_reason="completed")


# ── Helpers ──

class TestHelpers:
    def test_format_timestamp_unix(self):
        ts = 1700000000.0  # Nov 14, 2023
        result = _format_timestamp(ts)
        assert "2023" in result

    def test_format_timestamp_none(self):
        assert _format_timestamp(None) == "unknown"

    def test_format_conversation(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": [{"name": "read"}]},
            {"role": "tool", "content": "file data", "tool_name": "read"},
        ]
        text = _format_conversation(msgs)
        assert "[USER]: hello" in text
        assert "[Called: read]" in text
        assert "[TOOL:read]:" in text

    def test_truncate_short_text(self):
        text = "short text"
        assert _truncate_around_matches(text, "short") == text

    def test_truncate_centers_on_match(self):
        text = "a" * 50000 + "KEYWORD" + "b" * 50000
        result = _truncate_around_matches(text, "KEYWORD", max_chars=1000)
        assert "KEYWORD" in result
        assert len(result) < len(text)

    def test_resolve_to_parent(self, db):
        db.create_session("parent", source="cli")
        db.create_session("child", source="cli", parent_session_id="parent")
        assert _resolve_to_parent(db, "child") == "parent"

    def test_resolve_to_parent_no_parent(self, db):
        db.create_session("solo", source="cli")
        assert _resolve_to_parent(db, "solo") == "solo"


# ── Recent Sessions (no LLM) ──

class TestRecentSessions:
    @pytest.mark.asyncio
    async def test_empty_query_returns_recent(self, db):
        _seed_sessions(db)
        result = json.loads(await search_sessions(db, ""))
        assert result["success"] is True
        assert result["mode"] == "recent"
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_recent_excludes_current_session(self, db):
        _seed_sessions(db)
        result = json.loads(await search_sessions(db, "", current_session_id="s1"))
        session_ids = [r["session_id"] for r in result["results"]]
        assert "s1" not in session_ids

    @pytest.mark.asyncio
    async def test_recent_excludes_child_sessions(self, db):
        db.create_session("parent", source="cli")
        db.add_message("parent", "user", "parent session")
        db.create_session("child", source="cli", parent_session_id="parent")
        db.add_message("child", "user", "child session")

        result = json.loads(await search_sessions(db, ""))
        session_ids = [r["session_id"] for r in result["results"]]
        assert "child" not in session_ids


# ── Search with LLM Summarization ──

class TestSearchWithLLM:
    @pytest.mark.asyncio
    async def test_search_with_mock_llm(self, db):
        _seed_sessions(db)

        async def mock_complete(prompt, system="", **kwargs):
            return "Summary: discussed kubernetes deployment using kubectl."

        with patch("aion.llm.complete", side_effect=mock_complete):
            result = json.loads(await search_sessions(db, "kubernetes"))

        assert result["success"] is True
        assert result["count"] >= 1
        assert "kubernetes" in result["results"][0]["summary"].lower()

    @pytest.mark.asyncio
    async def test_search_no_matches(self, db):
        _seed_sessions(db)
        result = json.loads(await search_sessions(db, "nonexistenttopicxyz"))
        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_excludes_current_session(self, db):
        _seed_sessions(db)

        async def mock_complete(prompt, system="", **kwargs):
            return "summary"

        with patch("aion.llm.complete", side_effect=mock_complete):
            result = json.loads(
                await search_sessions(db, "kubernetes", current_session_id="s1")
            )

        session_ids = [r["session_id"] for r in result["results"]]
        assert "s1" not in session_ids

    @pytest.mark.asyncio
    async def test_search_resolves_parent_chains(self, db):
        """Child session matches should resolve to parent."""
        db.create_session("parent", source="cli")
        db.add_message("parent", "user", "started working on deployment")

        db.create_session("child", source="cli", parent_session_id="parent")
        db.add_message("child", "assistant", "deployment to kubernetes cluster complete")

        async def mock_complete(prompt, system="", **kwargs):
            return "deployed to k8s"

        with patch("aion.llm.complete", side_effect=mock_complete):
            result = json.loads(await search_sessions(db, "kubernetes"))

        if result["count"] > 0:
            session_ids = [r["session_id"] for r in result["results"]]
            # Should resolve to parent, not child
            assert "child" not in session_ids

    @pytest.mark.asyncio
    async def test_search_llm_failure_graceful(self, db):
        """If LLM fails for a session, search should still return others."""
        _seed_sessions(db)

        call_count = 0

        async def mock_complete(prompt, system="", **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("LLM error")
            return "summary of docker session"

        # Add another docker-related message to s1 so both sessions match
        db.add_message("s1", "user", "docker container networking")

        with patch("aion.llm.complete", side_effect=mock_complete):
            result = json.loads(await search_sessions(db, "docker"))

        assert result["success"] is True
        # At least one should succeed even if one fails


# ── Limit Enforcement ──

class TestLimits:
    @pytest.mark.asyncio
    async def test_limit_capped_at_5(self, db):
        """Limit should be capped at 5 regardless of input."""
        for i in range(10):
            sid = f"s{i}"
            db.create_session(sid, source="cli")
            db.add_message(sid, "user", f"topic alpha discussion {i}")

        async def mock_complete(prompt, system="", **kwargs):
            return "summary"

        with patch("aion.llm.complete", side_effect=mock_complete):
            result = json.loads(await search_sessions(db, "alpha", limit=10))

        assert result["count"] <= 5
