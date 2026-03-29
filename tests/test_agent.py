"""Tests for AionAgent — SDK message handling, system_prompt format, session flow."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_agent_sdk import (
    SystemMessage, AssistantMessage, UserMessage, ResultMessage, RateLimitEvent,
)
from claude_agent_sdk.types import (
    TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock, RateLimitInfo,
)

from aion.agent import AionAgent
from aion.config import AionConfig, MemoryConfig, AuditConfig


# ── Fixtures ──


@pytest.fixture
def tmp_home(tmp_path):
    """Isolated aion home directory."""
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("§ test memory entry")
    (memories / "USER.md").write_text("§ user likes brevity")
    return tmp_path


@pytest.fixture
def config(tmp_home):
    return AionConfig(
        model="claude-sonnet-4-20250514",
        max_turns=10,
        permission_mode="bypassPermissions",
        memory=MemoryConfig(char_limit=2200, user_char_limit=1375),
        audit=AuditConfig(enabled=True, log_tool_calls=True, redact_secrets=True),
        aion_home=tmp_home,
    )


@pytest.fixture
def agent(config):
    return AionAgent(config)


# ── Helpers: fake SDK messages using real SDK classes ──


def _system_init(session_id="cc-abc-123", model="claude-sonnet-4-20250514"):
    return SystemMessage(
        subtype="init",
        data={"session_id": session_id, "model": model, "tools": ["Read", "Write", "Bash"]},
    )


def _system_compact():
    return SystemMessage(subtype="compact_boundary", data={})


def _assistant_text(text, thinking=None):
    blocks = [TextBlock(text=text)]
    if thinking:
        blocks.append(ThinkingBlock(thinking=thinking, signature="sig"))
    return AssistantMessage(content=blocks, model="claude-sonnet-4-20250514")


def _assistant_tool_use(name, input_data, tool_id="tu-1"):
    block = ToolUseBlock(id=tool_id, name=name, input=input_data)
    return AssistantMessage(content=[block], model="claude-sonnet-4-20250514")


def _user_tool_result(tool_use_id, content, is_error=False):
    block = ToolResultBlock(tool_use_id=tool_use_id, content=content, is_error=is_error)
    return UserMessage(content=[block])


def _result(
    result_text="Done.",
    session_id="cc-abc-123",
    cost=0.05,
    num_turns=3,
    duration_ms=1500,
    stop_reason="end_turn",
    usage=None,
):
    return ResultMessage(
        subtype="success",
        result=result_text,
        session_id=session_id,
        total_cost_usd=cost,
        num_turns=num_turns,
        duration_ms=duration_ms,
        duration_api_ms=duration_ms,
        is_error=False,
        stop_reason=stop_reason,
        usage=usage,
    )


def _rate_limit(resets_at=1735689600):
    info = RateLimitInfo(status="rejected", resets_at=resets_at, utilization=0.95)
    return RateLimitEvent(rate_limit_info=info, uuid="rl-1", session_id="cc-abc-123")


class _FakeConversation:
    """Async iterable that mimics query() return value."""

    def __init__(self, messages):
        self._messages = messages

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for msg in self._messages:
            yield msg


# ── Tests ──


class TestSystemPromptFormat:
    """Task 1: system_prompt uses preset format."""

    @pytest.mark.asyncio
    async def test_uses_preset_with_memory(self, agent):
        """System prompt should use CC preset with memory appended."""
        captured_options = {}

        def mock_query(prompt, options):
            captured_options["system_prompt"] = options.system_prompt
            captured_options["model"] = options.model
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hello"):
                pass

        sp = captured_options["system_prompt"]
        assert sp["type"] == "preset"
        assert sp["preset"] == "claude_code"
        assert "append" in sp
        # Memory should be non-empty since we wrote files
        assert len(sp["append"]) > 0

    @pytest.mark.asyncio
    async def test_preset_without_memory(self, tmp_path):
        """When no memory files exist, preset still used but no append."""
        memories = tmp_path / "memories"
        memories.mkdir()
        config = AionConfig(
            aion_home=tmp_path,
            memory=MemoryConfig(),
            audit=AuditConfig(redact_secrets=False),
        )
        agent = AionAgent(config)
        captured_options = {}

        def mock_query(prompt, options):
            captured_options["system_prompt"] = options.system_prompt
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hello"):
                pass

        sp = captured_options["system_prompt"]
        assert sp["type"] == "preset"
        assert sp["preset"] == "claude_code"
        assert "append" not in sp


class TestMessageHandling:
    """Task 2: All message types handled."""

    @pytest.mark.asyncio
    async def test_system_init(self, agent):
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([_system_init("cc-99"), _result(session_id="cc-99")])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("hi"):
                msgs.append(m)

        init = msgs[0]
        assert init["type"] == "system"
        assert init["subtype"] == "init"
        assert init["session_id"] == "cc-99"
        assert init["model"] == "claude-sonnet-4-20250514"
        assert "Read" in init["tools"]

    @pytest.mark.asyncio
    async def test_assistant_with_thinking(self, agent):
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([
                _system_init(),
                _assistant_text("hello", thinking="let me think..."),
                _result(),
            ])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("hi"):
                msgs.append(m)

        assistant = msgs[1]
        assert assistant["type"] == "assistant"
        assert assistant["content"] == "hello"
        assert assistant["thinking"] == ["let me think..."]

    @pytest.mark.asyncio
    async def test_assistant_tool_use(self, agent):
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([
                _system_init(),
                _assistant_tool_use("Read", {"path": "/tmp/x"}, "tu-42"),
                _result(),
            ])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("read file"):
                msgs.append(m)

        assistant = msgs[1]
        assert assistant["type"] == "assistant"
        assert assistant["tool_uses"][0]["name"] == "Read"
        assert assistant["tool_uses"][0]["id"] == "tu-42"

    @pytest.mark.asyncio
    async def test_user_tool_result(self, agent):
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([
                _system_init(),
                _user_tool_result("tu-42", "file contents here"),
                _result(),
            ])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("hi"):
                msgs.append(m)

        user = msgs[1]
        assert user["type"] == "user"
        assert user["tool_results"][0]["tool_use_id"] == "tu-42"
        assert user["tool_results"][0]["content"] == "file contents here"
        assert user["tool_results"][0]["is_error"] is False

    @pytest.mark.asyncio
    async def test_result_metadata(self, agent):
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=200,
            cache_creation_input_tokens=100,
        )
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([
                _system_init(),
                _result(
                    result_text="All done",
                    cost=0.12,
                    num_turns=5,
                    duration_ms=3000,
                    stop_reason="end_turn",
                    usage=usage,
                ),
            ])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("do it"):
                msgs.append(m)

        res = msgs[1]
        assert res["type"] == "result"
        assert res["subtype"] == "success"
        assert res["cost_usd"] == 0.12
        assert res["num_turns"] == 5
        assert res["duration_api_ms"] == 3000
        assert res["stop_reason"] == "end_turn"
        assert res["usage"]["input_tokens"] == 1000
        assert res["usage"]["output_tokens"] == 500
        assert res["usage"]["cache_read"] == 200
        assert res["usage"]["cache_write"] == 100

    @pytest.mark.asyncio
    async def test_rate_limit_event(self, agent):
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([
                _system_init(),
                _rate_limit(resets_at=1748736000),
                _result(),
            ])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("hi"):
                msgs.append(m)

        rl = msgs[1]
        assert rl["type"] == "rate_limit_event"
        assert rl["rate_limit_info"]["status"] == "rejected"
        assert rl["rate_limit_info"]["resets_at"] == 1748736000
        assert rl["rate_limit_info"]["utilization"] == 0.95


class TestCompactionTracking:
    """Task 3: Compaction events create child sessions."""

    @pytest.mark.asyncio
    async def test_compact_boundary_creates_child(self, agent):
        def mock_query(prompt, options):
            return _FakeConversation([
                _system_init(),
                _system_compact(),
                _result(),
            ])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("long task"):
                pass

        # Should have 2 sessions: original + child from compaction
        recent = agent.sessions.recent_sessions(limit=5)
        assert len(recent) == 2
        # Most recent (child) should have parent_session_id set
        child = recent[0]
        parent = recent[1]
        assert child["parent_session_id"] == parent["id"]


class TestSessionContinuation:
    """Task 4: continue_session() reuses CC session ID."""

    @pytest.mark.asyncio
    async def test_continue_passes_resume(self, agent):
        captured = {}

        def mock_query(prompt, options):
            captured["resume"] = getattr(options, "resume", None)
            return _FakeConversation([_system_init("cc-continued"), _result(session_id="cc-continued")])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.continue_session("keep going", cc_session_id="cc-original"):
                pass

        assert captured["resume"] == "cc-original"

    @pytest.mark.asyncio
    async def test_continue_stores_new_session(self, agent):
        def mock_query(prompt, options):
            return _FakeConversation([_system_init("cc-new"), _result(session_id="cc-new", cost=0.03)])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.continue_session("more", cc_session_id="cc-prev"):
                pass

        recent = agent.sessions.recent_sessions(limit=1)
        assert len(recent) == 1
        sess = recent[0]
        assert sess["cc_session_id"] == "cc-new"
        assert sess["cost_usd"] == 0.03


class TestTokenTracking:
    """Task 5: Usage data extracted from ResultMessage."""

    @pytest.mark.asyncio
    async def test_cost_stored_in_session(self, agent):
        def mock_query(prompt, options):
            return _FakeConversation([_system_init(), _result(cost=0.42, stop_reason="end_turn")])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("expensive task"):
                pass

        recent = agent.sessions.recent_sessions(limit=1)
        sess = recent[0]
        assert sess["cost_usd"] == 0.42

    @pytest.mark.asyncio
    async def test_end_reason_stored(self, agent):
        def mock_query(prompt, options):
            return _FakeConversation([_system_init(), _result(stop_reason="max_turns")])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("long task"):
                pass

        recent = agent.sessions.recent_sessions(limit=1)
        sess = agent.sessions.get_session(recent[0]["id"])
        assert sess["end_reason"] == "max_turns"

    @pytest.mark.asyncio
    async def test_usage_dict_in_result(self, agent):
        """Result message should include parsed usage breakdown."""
        usage_dict = {"input_tokens": 500, "output_tokens": 200}
        msgs = []

        def mock_query(prompt, options):
            return _FakeConversation([_system_init(), _result(usage=usage_dict)])

        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("hi"):
                msgs.append(m)

        res = [m for m in msgs if m["type"] == "result"][0]
        assert res["usage"] == usage_dict


class TestModelOverride:
    """Task 6: model param overrides config."""

    @pytest.mark.asyncio
    async def test_model_override_in_run(self, agent):
        captured = {}

        def mock_query(prompt, options):
            captured["model"] = options.model
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hi", model="claude-opus-4-20250514"):
                pass

        assert captured["model"] == "claude-opus-4-20250514"

    @pytest.mark.asyncio
    async def test_default_model_from_config(self, agent):
        captured = {}

        def mock_query(prompt, options):
            captured["model"] = options.model
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hi"):
                pass

        assert captured["model"] == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_model_override_in_continue(self, agent):
        captured = {}

        def mock_query(prompt, options):
            captured["model"] = options.model
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.continue_session("hi", "cc-1", model="claude-haiku-4-5-20251001"):
                pass

        assert captured["model"] == "claude-haiku-4-5-20251001"


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_sdk_error_yields_error_dict(self, agent):
        class _ErrorConversation:
            def __aiter__(self):
                return self._aiter()
            async def _aiter(self):
                yield _system_init()
                raise RuntimeError("connection lost")

        def mock_query(prompt, options):
            return _ErrorConversation()

        msgs = []
        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("hi"):
                msgs.append(m)

        error = [m for m in msgs if m["type"] == "error"]
        assert len(error) == 1
        assert "connection lost" in error[0]["error"]

        # Session should still be ended with error reason
        recent = agent.sessions.recent_sessions(limit=1)
        sess = agent.sessions.get_session(recent[0]["id"])
        assert sess["end_reason"] == "error"


class TestRedaction:
    @pytest.mark.asyncio
    async def test_redaction_applied_to_content(self, tmp_path):
        """When redact_secrets is True, secrets in content are redacted."""
        memories = tmp_path / "memories"
        memories.mkdir()
        (memories / "MEMORY.md").write_text("")
        (memories / "USER.md").write_text("")
        config = AionConfig(
            aion_home=tmp_path,
            memory=MemoryConfig(),
            audit=AuditConfig(redact_secrets=True),
        )
        agent = AionAgent(config)

        def mock_query(prompt, options):
            msg = _assistant_text("key is sk-ant-abcdefghijklmnopqrstuvwx")
            return _FakeConversation([_system_init(), msg, _result()])

        msgs = []
        with patch("aion.agent.query", side_effect=mock_query):
            async for m in agent.run("show key"):
                msgs.append(m)

        assistant = [m for m in msgs if m["type"] == "assistant"][0]
        assert "sk-ant-" not in assistant["content"]
        assert "[REDACTED" in assistant["content"]
