"""Pydantic v2 schemas for structured LLM output."""

from pydantic import BaseModel, Field


class SessionTitle(BaseModel):
    """Generated title for a conversation session."""

    title: str = Field(description="Short, descriptive title (3-8 words)")


class SessionSummary(BaseModel):
    """Summary of a past session for search results."""

    title: str = Field(description="Short title for the session")
    summary: str = Field(
        description="2-4 sentence summary of what was discussed/accomplished"
    )
    relevance: float = Field(
        ge=0.0, le=1.0, description="Relevance to the search query, 0-1"
    )


class SearchResult(BaseModel):
    """Container for multiple session summaries."""

    sessions: list[SessionSummary]
