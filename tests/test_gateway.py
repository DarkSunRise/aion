"""Tests for gateway components."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aion.utils.ansi import strip_ansi
from aion.gateway.base import GatewayMessage, split_message
from aion.gateway.session import SessionSource, build_session_context_prompt
from aion.gateway.config import (
    GatewayConfig,
    TelegramConfig,
    SlackConfig,
    _interpolate_env,
)


# ── ANSI stripping ──


class TestStripAnsi:
    def test_no_ansi(self):
        assert strip_ansi("hello world") == "hello world"

    def test_strip_colors(self):
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_strip_bold(self):
        assert strip_ansi("\x1b[1mbold\x1b[0m") == "bold"

    def test_strip_cursor_movement(self):
        assert strip_ansi("\x1b[2Aup\x1b[3Bdown") == "updown"

    def test_strip_osc_hyperlink(self):
        # OSC 8 hyperlink: ESC]8;;url BEL text ESC]8;; BEL
        text = "\x1b]8;;https://example.com\x07link\x1b]8;;\x07"
        assert strip_ansi(text) == "link"

    def test_strip_mixed(self):
        text = "\x1b[32m✓\x1b[0m Tests passed \x1b[1m(3/3)\x1b[0m"
        assert strip_ansi(text) == "✓ Tests passed (3/3)"

    def test_empty_string(self):
        assert strip_ansi("") == ""

    def test_multiline(self):
        text = "\x1b[31mline1\x1b[0m\nline2\n\x1b[32mline3\x1b[0m"
        assert strip_ansi(text) == "line1\nline2\nline3"


# ── GatewayMessage ──


class TestGatewayMessage:
    def test_creation(self):
        msg = GatewayMessage(
            text="hello",
            sender_id="123",
            chat_id="456",
            platform="telegram",
        )
        assert msg.text == "hello"
        assert msg.sender_id == "123"
        assert msg.chat_id == "456"
        assert msg.platform == "telegram"
        assert msg.metadata == {}

    def test_creation_with_metadata(self):
        msg = GatewayMessage(
            text="hi",
            sender_id="u1",
            chat_id="c1",
            platform="slack",
            sender_name="Alice",
            metadata={"thread_ts": "123.456"},
        )
        assert msg.sender_name == "Alice"
        assert msg.metadata["thread_ts"] == "123.456"


# ── Message splitting ──


class TestSplitMessage:
    def test_short_message(self):
        assert split_message("hello", 100) == ["hello"]

    def test_exact_limit(self):
        text = "a" * 100
        assert split_message(text, 100) == [text]

    def test_split_at_paragraph(self):
        text = "first paragraph\n\nsecond paragraph"
        chunks = split_message(text, 20)
        assert len(chunks) == 2
        assert chunks[0] == "first paragraph"
        assert chunks[1] == "second paragraph"

    def test_split_at_newline(self):
        text = "line one\nline two is a bit longer"
        chunks = split_message(text, 15)
        assert len(chunks) >= 2
        assert "line one" in chunks[0]

    def test_split_at_space(self):
        text = "word1 word2 word3 word4"
        chunks = split_message(text, 12)
        assert all(len(c) <= 12 for c in chunks)

    def test_hard_split(self):
        text = "a" * 200
        chunks = split_message(text, 50)
        assert all(len(c) <= 50 for c in chunks)
        assert "".join(chunks) == text

    def test_telegram_limit(self):
        text = "x" * 8000
        chunks = split_message(text, 4096)
        assert all(len(c) <= 4096 for c in chunks)

    def test_slack_limit(self):
        text = "x" * 8000
        chunks = split_message(text, 4000)
        assert all(len(c) <= 4000 for c in chunks)


# ── SessionSource ──


class TestSessionSource:
    def test_dm_description(self):
        src = SessionSource(
            platform="telegram",
            user_id="123",
            user_name="Kostya",
            chat_type="dm",
        )
        assert src.description == "DM with Kostya"

    def test_group_description(self):
        src = SessionSource(
            platform="telegram",
            user_id="123",
            chat_type="group",
            chat_name="Dev Chat",
        )
        assert src.description == "group: Dev Chat"

    def test_channel_description(self):
        src = SessionSource(
            platform="slack",
            user_id="U123",
            chat_type="channel",
            chat_name="#general",
        )
        assert src.description == "channel: #general"

    def test_cli_description(self):
        src = SessionSource(platform="cli", user_id="local")
        assert src.description == "CLI terminal"


# ── build_session_context_prompt ──


class TestBuildSessionContextPrompt:
    def test_basic_telegram_dm(self):
        src = SessionSource(
            platform="telegram",
            user_id="123",
            user_name="Kostya",
            chat_type="dm",
        )
        prompt = build_session_context_prompt(src, ["telegram"])
        assert "Telegram" in prompt
        assert "DM with Kostya" in prompt
        assert "**User:** Kostya" in prompt
        assert "telegram: Connected" in prompt

    def test_slack_includes_platform_notes(self):
        src = SessionSource(
            platform="slack",
            user_id="U123",
            user_name="Alice",
            chat_type="dm",
        )
        prompt = build_session_context_prompt(src, ["slack"])
        assert "Platform notes" in prompt
        assert "Slack" in prompt

    def test_multiple_platforms(self):
        src = SessionSource(
            platform="telegram",
            user_id="123",
            chat_type="dm",
        )
        prompt = build_session_context_prompt(src, ["telegram", "slack"])
        assert "telegram: Connected" in prompt
        assert "slack: Connected" in prompt


# ── Config ──


class TestInterpolateEnv:
    def test_simple_var(self):
        os.environ["TEST_AION_VAR"] = "hello"
        try:
            assert _interpolate_env("${TEST_AION_VAR}") == "hello"
        finally:
            del os.environ["TEST_AION_VAR"]

    def test_missing_var_unchanged(self):
        result = _interpolate_env("${NONEXISTENT_AION_VAR_12345}")
        assert result == "${NONEXISTENT_AION_VAR_12345}"

    def test_no_vars(self):
        assert _interpolate_env("plain text") == "plain text"


class TestTelegramConfig:
    def test_from_dict(self):
        cfg = TelegramConfig.from_dict({
            "token": "abc123",
            "allowed_users": ["111", 222],
        })
        assert cfg.token == "abc123"
        assert cfg.allowed_users == ["111", "222"]

    def test_from_dict_defaults(self):
        cfg = TelegramConfig.from_dict({})
        assert cfg.token == ""
        assert cfg.allowed_users == []

    def test_env_interpolation(self):
        os.environ["TEST_TG_TOKEN"] = "bot_token_123"
        try:
            cfg = TelegramConfig.from_dict({"token": "${TEST_TG_TOKEN}"})
            assert cfg.token == "bot_token_123"
        finally:
            del os.environ["TEST_TG_TOKEN"]


class TestSlackConfig:
    def test_from_dict(self):
        cfg = SlackConfig.from_dict({
            "bot_token": "xoxb-test",
            "app_token": "xapp-test",
            "allowed_users": ["U1"],
            "allowed_channels": ["C1"],
        })
        assert cfg.bot_token == "xoxb-test"
        assert cfg.app_token == "xapp-test"
        assert cfg.allowed_users == ["U1"]
        assert cfg.allowed_channels == ["C1"]

    def test_from_dict_defaults(self):
        cfg = SlackConfig.from_dict({})
        assert cfg.bot_token == ""
        assert cfg.app_token == ""


class TestGatewayConfig:
    def test_from_dict_both(self):
        cfg = GatewayConfig.from_dict({
            "telegram": {"token": "tg_token"},
            "slack": {"bot_token": "xoxb-x", "app_token": "xapp-x"},
        })
        assert cfg.telegram is not None
        assert cfg.telegram.token == "tg_token"
        assert cfg.slack is not None
        assert cfg.slack.bot_token == "xoxb-x"
        assert cfg.has_any

    def test_from_dict_empty(self):
        cfg = GatewayConfig.from_dict({})
        assert cfg.telegram is None
        assert cfg.slack is None
        assert not cfg.has_any

    def test_connected_platforms(self):
        cfg = GatewayConfig.from_dict({
            "telegram": {"token": "tg"},
            "slack": {"bot_token": "xoxb"},
        })
        platforms = cfg.connected_platforms
        assert "telegram" in platforms
        assert "slack" in platforms

    def test_connected_platforms_empty_token(self):
        cfg = GatewayConfig.from_dict({
            "telegram": {"token": ""},
        })
        assert cfg.connected_platforms == []


# ── Telegram adapter (mock-based) ──


class TestTelegramAdapter:
    @pytest.fixture
    def adapter(self):
        from aion.gateway.adapters.telegram import TelegramAdapter

        config = TelegramConfig(token="test_token", allowed_users=["123"])
        return TelegramAdapter(config)

    def test_is_allowed(self, adapter):
        assert adapter._is_allowed(123) is True
        assert adapter._is_allowed(999) is False

    def test_is_allowed_empty_list(self):
        from aion.gateway.adapters.telegram import TelegramAdapter

        config = TelegramConfig(token="test", allowed_users=[])
        adapter = TelegramAdapter(config)
        assert adapter._is_allowed(999) is True

    def test_build_source_dm(self, adapter):
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.full_name = "Test User"
        update.effective_chat.id = 123
        update.effective_chat.type = "private"
        update.effective_chat.title = None

        source = adapter._build_source(update)
        assert source.platform == "telegram"
        assert source.user_id == "123"
        assert source.user_name == "Test User"
        assert source.chat_type == "dm"

    def test_build_source_group(self, adapter):
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.full_name = "Test"
        update.effective_chat.id = -100
        update.effective_chat.type = "supergroup"
        update.effective_chat.title = "Dev Group"

        source = adapter._build_source(update)
        assert source.chat_type == "group"
        assert source.chat_name == "Dev Group"


# ── Slack adapter (mock-based) ──


class TestSlackAdapter:
    @pytest.fixture
    def adapter(self):
        from aion.gateway.adapters.slack import SlackAdapter

        config = SlackConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            allowed_users=["U123"],
            allowed_channels=["C456"],
        )
        return SlackAdapter(config)

    def test_is_allowed(self, adapter):
        assert adapter._is_allowed("U123", "C456") is True
        assert adapter._is_allowed("U999", "C456") is False
        assert adapter._is_allowed("U123", "C999") is False

    def test_is_allowed_empty_lists(self):
        from aion.gateway.adapters.slack import SlackAdapter

        config = SlackConfig(bot_token="xoxb", app_token="xapp")
        adapter = SlackAdapter(config)
        assert adapter._is_allowed("anyone", "anywhere") is True

    def test_build_source_dm(self, adapter):
        source = adapter._build_source(
            user_id="U123",
            user_name="Alice",
            channel_id="D456",
            channel_type="im",
            thread_ts=None,
        )
        assert source.platform == "slack"
        assert source.user_id == "U123"
        assert source.chat_type == "dm"

    def test_build_source_channel(self, adapter):
        source = adapter._build_source(
            user_id="U123",
            user_name="Alice",
            channel_id="C456",
            channel_type="channel",
            thread_ts="1234.5678",
        )
        assert source.chat_type == "channel"
        assert source.thread_id == "1234.5678"

    @pytest.mark.asyncio
    async def test_handle_ignores_bot_messages(self, adapter):
        adapter.on_message = AsyncMock()
        await adapter._handle_message_event({
            "bot_id": "B123",
            "text": "hello",
            "user": "U123",
            "channel": "C456",
        })
        adapter.on_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_ignores_edits(self, adapter):
        adapter.on_message = AsyncMock()
        await adapter._handle_message_event({
            "subtype": "message_changed",
            "text": "hello",
            "user": "U123",
            "channel": "C456",
        })
        adapter.on_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_ignores_unauthorized(self, adapter):
        adapter.on_message = AsyncMock()
        await adapter._handle_message_event({
            "text": "hello",
            "user": "U999",
            "channel": "C456",
            "channel_type": "im",
            "ts": "1234",
        })
        adapter.on_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_dm_message(self, adapter):
        adapter.on_message = AsyncMock(return_value="response text")
        adapter._app = MagicMock()
        adapter._app.client.chat_postMessage = AsyncMock()
        adapter._app.client.users_info = AsyncMock(return_value={
            "user": {"profile": {"display_name": "Alice"}}
        })

        await adapter._handle_message_event({
            "text": "hello aion",
            "user": "U123",
            "channel": "C456",
            "channel_type": "im",
            "ts": "1234.5678",
        })

        adapter.on_message.assert_called_once()
        call_msg = adapter.on_message.call_args[0][0]
        assert call_msg.text == "hello aion"
        assert call_msg.platform == "slack"

    @pytest.mark.asyncio
    async def test_handle_channel_needs_mention(self, adapter):
        adapter.on_message = AsyncMock()
        adapter._bot_user_id = "B001"

        # No mention → ignored
        await adapter._handle_message_event({
            "text": "just chatting",
            "user": "U123",
            "channel": "C456",
            "channel_type": "channel",
            "ts": "1234",
        })
        adapter.on_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_channel_with_mention(self, adapter):
        adapter.on_message = AsyncMock(return_value="done")
        adapter._bot_user_id = "B001"
        adapter._app = MagicMock()
        adapter._app.client.chat_postMessage = AsyncMock()
        adapter._app.client.users_info = AsyncMock(return_value={
            "user": {"profile": {"display_name": "Alice"}}
        })

        await adapter._handle_message_event({
            "text": "<@B001> do something",
            "user": "U123",
            "channel": "C456",
            "channel_type": "channel",
            "ts": "1234",
        })

        adapter.on_message.assert_called_once()
        call_msg = adapter.on_message.call_args[0][0]
        assert call_msg.text == "do something"
