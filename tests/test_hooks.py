"""Tests for SDK lifecycle hooks."""

import pytest
from unittest.mock import AsyncMock, patch

from claude_agent_sdk import HookMatcher

from aion.hooks import AionHooks
from aion.agent import AionAgent
from aion.config import AionConfig, MemoryConfig, AuditConfig


# ── Fixtures ──


@pytest.fixture
def hooks():
    return AionHooks()


@pytest.fixture
def hooks_with_notify():
    callback = AsyncMock()
    return AionHooks(notify_callback=callback), callback


@pytest.fixture
def tmp_home(tmp_path):
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("§ test")
    (memories / "USER.md").write_text("")
    return tmp_path


@pytest.fixture
def config(tmp_home):
    return AionConfig(
        aion_home=tmp_home,
        memory=MemoryConfig(),
        audit=AuditConfig(redact_secrets=False),
    )


# ── build_hooks_dict ──


class TestBuildHooksDict:
    def test_returns_correct_keys(self, hooks):
        d = hooks.build_hooks_dict()
        expected_keys = {
            "Stop", "Notification", "PreCompact",
            "PreToolUse", "PostToolUse",
            "SubagentStart", "SubagentStop",
        }
        assert set(d.keys()) == expected_keys

    def test_values_are_hook_matcher_lists(self, hooks):
        d = hooks.build_hooks_dict()
        for key, matchers in d.items():
            assert isinstance(matchers, list), f"{key} should be a list"
            assert len(matchers) == 1, f"{key} should have 1 matcher"
            assert isinstance(matchers[0], HookMatcher), f"{key}[0] should be HookMatcher"

    def test_each_matcher_has_one_hook(self, hooks):
        d = hooks.build_hooks_dict()
        for key, matchers in d.items():
            assert len(matchers[0].hooks) == 1, f"{key} matcher should have 1 hook"
            assert callable(matchers[0].hooks[0]), f"{key} hook should be callable"


# ── Individual hook callbacks ──


class TestHookCallbacks:
    @pytest.mark.asyncio
    async def test_on_stop(self, hooks):
        result = await hooks._on_stop(
            {"session_id": "s1", "hook_event_name": "Stop", "stop_hook_active": True},
            None,
            None,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_on_notification_without_callback(self, hooks):
        result = await hooks._on_notification(
            {"session_id": "s1", "message": "working on it", "notification_type": "info"},
            None,
            None,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_on_notification_with_callback(self, hooks_with_notify):
        hooks, callback = hooks_with_notify
        await hooks._on_notification(
            {"session_id": "s1", "message": "done", "notification_type": "info"},
            None,
            None,
        )
        callback.assert_called_once_with("s1", "done")

    @pytest.mark.asyncio
    async def test_on_notification_with_title(self, hooks_with_notify):
        hooks, callback = hooks_with_notify
        await hooks._on_notification(
            {"session_id": "s1", "message": "hi", "title": "Status", "notification_type": "info"},
            None,
            None,
        )
        callback.assert_called_once_with("s1", "hi")

    @pytest.mark.asyncio
    async def test_on_pre_compact(self, hooks):
        result = await hooks._on_pre_compact(
            {"trigger": "auto", "custom_instructions": None},
            None,
            None,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_on_pre_tool_use(self, hooks):
        result = await hooks._on_pre_tool_use(
            {"tool_name": "Read", "tool_input": {"path": "/tmp"}},
            "Read",
            None,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_on_post_tool_use(self, hooks):
        result = await hooks._on_post_tool_use(
            {"tool_name": "Read"},
            "Read",
            None,
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_on_subagent_start(self, hooks):
        result = await hooks._on_subagent_start({}, None, None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_on_subagent_stop(self, hooks):
        result = await hooks._on_subagent_stop({}, None, None)
        assert result == {}


# ── Hooks wired into agent ──


class TestHooksInAgent:
    def test_agent_creates_hooks(self, config):
        agent = AionAgent(config)
        assert isinstance(agent._hooks, AionHooks)

    def test_agent_with_notify_callback(self, config):
        cb = AsyncMock()
        agent = AionAgent(config, notify_callback=cb)
        assert agent._hooks._notify is cb

    @pytest.mark.asyncio
    async def test_hooks_passed_to_options_in_run(self, config):
        agent = AionAgent(config)
        captured = {}

        from tests.test_agent import _FakeConversation, _system_init, _result

        def mock_query(prompt, options):
            captured["hooks"] = options.hooks
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hi"):
                pass

        assert captured["hooks"] is not None
        assert "Stop" in captured["hooks"]
        assert "Notification" in captured["hooks"]
        assert "PreCompact" in captured["hooks"]

    @pytest.mark.asyncio
    async def test_hooks_passed_to_options_in_continue(self, config):
        agent = AionAgent(config)
        captured = {}

        from tests.test_agent import _FakeConversation, _system_init, _result

        def mock_query(prompt, options):
            captured["hooks"] = options.hooks
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.continue_session("hi", "cc-1"):
                pass

        assert captured["hooks"] is not None
        assert "Stop" in captured["hooks"]
