"""Tests for the auxiliary LLM module."""

import json
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from aion.llm import complete, complete_structured
from aion.schemas import SessionTitle, SessionSummary


class FakeResultMessage:
    """Mimics claude_agent_sdk.ResultMessage."""

    def __init__(self, result: str, structured_output=None):
        self.result = result
        self.structured_output = structured_output


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


# ── complete_structured tests ──


@pytest.mark.asyncio
async def test_structured_from_structured_output():
    """SDK returns pre-parsed structured_output → validate into model."""
    data = {"title": "K8s Deploy Fix"}

    async def _fake(**kwargs):
        yield FakeResultMessage(result=None, structured_output=data)

    with patch("aion.llm.query", side_effect=_fake):
        result = await complete_structured("summarize", SessionTitle)

    assert isinstance(result, SessionTitle)
    assert result.title == "K8s Deploy Fix"


@pytest.mark.asyncio
async def test_structured_fallback_to_result_json():
    """structured_output is None but result contains valid JSON → parse it."""
    data = {"title": "Docker Fix", "summary": "Fixed networking.", "relevance": 0.9}

    async def _fake(**kwargs):
        yield FakeResultMessage(result=json.dumps(data), structured_output=None)

    with patch("aion.llm.query", side_effect=_fake):
        result = await complete_structured("summarize", SessionSummary)

    assert isinstance(result, SessionSummary)
    assert result.title == "Docker Fix"
    assert result.relevance == 0.9


@pytest.mark.asyncio
async def test_structured_returns_none_on_invalid_json():
    """Result text is not valid JSON → returns None."""
    async def _fake(**kwargs):
        yield FakeResultMessage(result="not json at all")

    with patch("aion.llm.query", side_effect=_fake):
        result = await complete_structured("test", SessionTitle)

    assert result is None


@pytest.mark.asyncio
async def test_structured_returns_none_on_validation_error():
    """Result is valid JSON but fails schema validation → returns None."""
    bad_data = {"title": "x", "summary": "y", "relevance": 5.0}  # relevance > 1

    async def _fake(**kwargs):
        yield FakeResultMessage(result=json.dumps(bad_data))

    with patch("aion.llm.query", side_effect=_fake):
        result = await complete_structured("test", SessionSummary)

    assert result is None


@pytest.mark.asyncio
async def test_structured_returns_none_on_exception():
    """Query raises → returns None."""
    async def _fake(**kwargs):
        raise RuntimeError("boom")
        yield

    with patch("aion.llm.query", side_effect=_fake):
        result = await complete_structured("test", SessionTitle)

    assert result is None


@pytest.mark.asyncio
async def test_structured_passes_output_format():
    """Verify output_format is set with the schema's JSON schema."""
    calls = []

    async def _capture(**kwargs):
        calls.append(kwargs)
        yield FakeResultMessage(
            result=None,
            structured_output={"title": "Test"},
        )

    with patch("aion.llm.query", side_effect=_capture):
        await complete_structured("test", SessionTitle)

    opts = calls[0]["options"]
    assert opts.output_format["type"] == "json_schema"
    assert "properties" in opts.output_format["schema"]
    assert "title" in opts.output_format["schema"]["properties"]
