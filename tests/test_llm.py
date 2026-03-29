"""Tests for the auxiliary LLM module."""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from aion.llm import complete


class FakeResultMessage:
    """Mimics claude_agent_sdk.ResultMessage."""

    def __init__(self, result: str):
        self.result = result


class FakeSystemMessage:
    """Message without a result attribute."""
    pass


async def _fake_query_success(**kwargs):
    """Async generator yielding a system msg then a result."""
    yield FakeSystemMessage()
    yield FakeResultMessage("summary of the session")


async def _fake_query_none(**kwargs):
    """Async generator yielding a result with None."""
    yield FakeResultMessage(None)


async def _fake_query_error(**kwargs):
    """Async generator that raises."""
    raise RuntimeError("connection failed")
    yield  # make it a generator  # noqa: E501


@pytest.mark.asyncio
async def test_complete_extracts_result():
    with patch("aion.llm.query", side_effect=_fake_query_success):
        result = await complete("summarize this")
    assert result == "summary of the session"


@pytest.mark.asyncio
async def test_complete_with_system_prompt():
    calls = []

    async def _capture(**kwargs):
        calls.append(kwargs)
        yield FakeResultMessage("ok")

    with patch("aion.llm.query", side_effect=_capture):
        await complete("do thing", system="be concise")

    assert "be concise" in calls[0]["prompt"]
    assert "do thing" in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_complete_returns_none_on_error():
    with patch("aion.llm.query", side_effect=_fake_query_error):
        result = await complete("test")
    assert result is None


@pytest.mark.asyncio
async def test_complete_returns_none_when_no_result():
    with patch("aion.llm.query", side_effect=_fake_query_none):
        result = await complete("test")
    assert result is None


@pytest.mark.asyncio
async def test_complete_passes_model_option():
    calls = []

    async def _capture(**kwargs):
        calls.append(kwargs)
        yield FakeResultMessage("ok")

    with patch("aion.llm.query", side_effect=_capture):
        await complete("test", model="claude-haiku-4-5-20251001")

    opts = calls[0]["options"]
    assert opts.model == "claude-haiku-4-5-20251001"
    assert opts.max_turns == 1
    assert opts.allowed_tools == []
