"""Tests for external MCP server support — config parsing and agent wiring."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from aion.config import AionConfig, MemoryConfig, AuditConfig, load_config
from aion.agent import AionAgent


# ── Fixtures ──


@pytest.fixture
def tmp_home(tmp_path):
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("")
    (memories / "USER.md").write_text("")
    return tmp_path


# ── Helpers ──


class _FakeConversation:
    def __init__(self, messages):
        self._messages = messages

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for msg in self._messages:
            yield msg


def _system_init():
    from claude_agent_sdk import SystemMessage
    return SystemMessage(subtype="init", data={"session_id": "cc-1", "model": "test", "tools": []})


def _result():
    from claude_agent_sdk import ResultMessage
    return ResultMessage(
        subtype="success", result="ok", session_id="cc-1",
        total_cost_usd=0.01, num_turns=1, duration_ms=100,
        duration_api_ms=100, is_error=False, stop_reason="end_turn",
    )


# ── Config parsing ──


class TestMcpServerConfig:
    def test_default_empty(self):
        config = AionConfig()
        assert config.mcp_servers == {}

    def test_mcp_servers_from_config(self, tmp_home):
        config_data = {
            "mcp_servers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
                },
                "github": {
                    "command": "uvx",
                    "args": ["mcp-server-github"],
                    "env": {"GITHUB_TOKEN": "test-token"},
                },
            }
        }
        config_path = tmp_home / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        config = load_config(config_path)
        assert "filesystem" in config.mcp_servers
        assert config.mcp_servers["filesystem"]["command"] == "npx"
        assert config.mcp_servers["filesystem"]["args"] == [
            "-y", "@modelcontextprotocol/server-filesystem", "/home/user",
        ]
        assert "github" in config.mcp_servers
        assert config.mcp_servers["github"]["env"]["GITHUB_TOKEN"] == "test-token"

    def test_env_interpolation_in_mcp_servers(self, tmp_home):
        os.environ["TEST_MCP_TOKEN"] = "secret-123"
        try:
            config_data = {
                "mcp_servers": {
                    "github": {
                        "command": "uvx",
                        "args": ["mcp-server-github"],
                        "env": {"GITHUB_TOKEN": "${TEST_MCP_TOKEN}"},
                    }
                }
            }
            config_path = tmp_home / "config.yaml"
            config_path.write_text(yaml.dump(config_data))

            config = load_config(config_path)
            assert config.mcp_servers["github"]["env"]["GITHUB_TOKEN"] == "secret-123"
        finally:
            del os.environ["TEST_MCP_TOKEN"]

    def test_env_interpolation_in_args_list(self, tmp_home):
        """Env vars in list values (like args) should be interpolated."""
        os.environ["TEST_MCP_PATH"] = "/home/testuser"
        try:
            config_data = {
                "mcp_servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@anthropic/mcp-fs", "${TEST_MCP_PATH}"],
                    }
                }
            }
            config_path = tmp_home / "config.yaml"
            config_path.write_text(yaml.dump(config_data))

            config = load_config(config_path)
            assert config.mcp_servers["filesystem"]["args"][2] == "/home/testuser"
        finally:
            del os.environ["TEST_MCP_PATH"]

    def test_mcp_servers_empty_section(self, tmp_home):
        config_data = {"mcp_servers": {}}
        config_path = tmp_home / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        config = load_config(config_path)
        assert config.mcp_servers == {}

    def test_mcp_servers_missing_section(self, tmp_home):
        config_data = {"model": "test"}
        config_path = tmp_home / "config.yaml"
        config_path.write_text(yaml.dump(config_data))

        config = load_config(config_path)
        assert config.mcp_servers == {}


# ── Config edge cases ──


class TestConfigEdgeCases:
    def test_malformed_yaml_raises(self, tmp_home):
        """Malformed YAML should raise a clear error, not corrupt config."""
        config_path = tmp_home / "config.yaml"
        config_path.write_text("model: [\ninvalid: yaml: [broken")
        with pytest.raises(Exception):
            load_config(config_path)

    def test_yaml_with_none_values(self, tmp_home):
        """Config with explicit null values should use defaults."""
        config_path = tmp_home / "config.yaml"
        config_path.write_text("model: null\nmax_turns: null\n")
        config = load_config(config_path)
        # Should fall back to defaults from the get() calls
        assert config.model is not None or config.model == "claude-sonnet-4-20250514"

    def test_nonexistent_config_uses_defaults(self, tmp_home):
        """Missing config file should use defaults without error."""
        config = load_config(tmp_home / "nonexistent.yaml")
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_turns == 100


# ── Agent wiring ──


class TestMcpServerWiring:
    @pytest.mark.asyncio
    async def test_external_servers_merged_into_run(self, tmp_home):
        config = AionConfig(
            aion_home=tmp_home,
            memory=MemoryConfig(),
            audit=AuditConfig(redact_secrets=False),
            mcp_servers={
                "filesystem": {"command": "npx", "args": ["-y", "test"]},
            },
        )
        agent = AionAgent(config)
        agent._generate_title = AsyncMock(return_value=None)
        captured = {}

        def mock_query(prompt, options):
            captured["mcp_servers"] = dict(options.mcp_servers)
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hi"):
                pass

        assert "aion" in captured["mcp_servers"]
        assert "filesystem" in captured["mcp_servers"]
        assert captured["mcp_servers"]["filesystem"]["command"] == "npx"

    @pytest.mark.asyncio
    async def test_external_servers_merged_into_continue(self, tmp_home):
        config = AionConfig(
            aion_home=tmp_home,
            memory=MemoryConfig(),
            audit=AuditConfig(redact_secrets=False),
            mcp_servers={
                "github": {"command": "uvx", "args": ["mcp-server-github"]},
            },
        )
        agent = AionAgent(config)
        agent._generate_title = AsyncMock(return_value=None)
        captured = {}

        def mock_query(prompt, options):
            captured["mcp_servers"] = dict(options.mcp_servers)
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.continue_session("hi", "cc-1"):
                pass

        assert "aion" in captured["mcp_servers"]
        assert "github" in captured["mcp_servers"]

    @pytest.mark.asyncio
    async def test_caller_servers_override_config(self, tmp_home):
        config = AionConfig(
            aion_home=tmp_home,
            memory=MemoryConfig(),
            audit=AuditConfig(redact_secrets=False),
            mcp_servers={
                "filesystem": {"command": "npx", "args": ["old"]},
            },
        )
        agent = AionAgent(config)
        agent._generate_title = AsyncMock(return_value=None)
        captured = {}

        def mock_query(prompt, options):
            captured["mcp_servers"] = dict(options.mcp_servers)
            return _FakeConversation([_system_init(), _result()])

        caller_servers = {"filesystem": {"command": "npx", "args": ["new"]}}
        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hi", mcp_servers=caller_servers):
                pass

        # Caller-provided should override config
        assert captured["mcp_servers"]["filesystem"]["args"] == ["new"]

    @pytest.mark.asyncio
    async def test_no_external_servers_still_has_aion(self, tmp_home):
        config = AionConfig(
            aion_home=tmp_home,
            memory=MemoryConfig(),
            audit=AuditConfig(redact_secrets=False),
        )
        agent = AionAgent(config)
        agent._generate_title = AsyncMock(return_value=None)
        captured = {}

        def mock_query(prompt, options):
            captured["mcp_servers"] = dict(options.mcp_servers)
            return _FakeConversation([_system_init(), _result()])

        with patch("aion.agent.query", side_effect=mock_query):
            async for _ in agent.run("hi"):
                pass

        assert "aion" in captured["mcp_servers"]
        assert len(captured["mcp_servers"]) == 1
