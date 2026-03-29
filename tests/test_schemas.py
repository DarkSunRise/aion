"""Tests for Pydantic v2 schemas."""

import pytest
from pydantic import ValidationError

from aion.schemas import SessionTitle, SessionSummary, SearchResult


class TestSessionTitle:
    def test_valid(self):
        t = SessionTitle(title="Kubernetes Deployment Fix")
        assert t.title == "Kubernetes Deployment Fix"

    def test_missing_title(self):
        with pytest.raises(ValidationError):
            SessionTitle()

    def test_wrong_type(self):
        with pytest.raises(ValidationError):
            SessionTitle(title=123)

    def test_json_schema(self):
        schema = SessionTitle.model_json_schema()
        assert schema["type"] == "object"
        assert "title" in schema["properties"]


class TestSessionSummary:
    def test_valid(self):
        s = SessionSummary(
            title="Docker Networking",
            summary="Fixed docker compose port mapping issue.",
            relevance=0.85,
        )
        assert s.title == "Docker Networking"
        assert s.relevance == 0.85

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            SessionSummary(title="x")

    def test_relevance_below_zero(self):
        with pytest.raises(ValidationError):
            SessionSummary(title="x", summary="y", relevance=-0.1)

    def test_relevance_above_one(self):
        with pytest.raises(ValidationError):
            SessionSummary(title="x", summary="y", relevance=1.1)

    def test_relevance_bounds(self):
        s0 = SessionSummary(title="x", summary="y", relevance=0.0)
        s1 = SessionSummary(title="x", summary="y", relevance=1.0)
        assert s0.relevance == 0.0
        assert s1.relevance == 1.0

    def test_json_schema(self):
        schema = SessionSummary.model_json_schema()
        assert "title" in schema["properties"]
        assert "summary" in schema["properties"]
        assert "relevance" in schema["properties"]


class TestSearchResult:
    def test_valid(self):
        sr = SearchResult(
            sessions=[
                SessionSummary(title="a", summary="b", relevance=0.5),
            ]
        )
        assert len(sr.sessions) == 1

    def test_empty_sessions(self):
        sr = SearchResult(sessions=[])
        assert sr.sessions == []

    def test_invalid_session_in_list(self):
        with pytest.raises(ValidationError):
            SearchResult(sessions=[{"title": "x"}])

    def test_json_schema(self):
        schema = SearchResult.model_json_schema()
        assert "sessions" in schema["properties"]
