# Session Prompt: Phase 0.0 — Structured Output Support

## Goal

Add structured output support to Aion's LLM layer. This is the foundation that
everything else builds on — aux calls (search summaries, titles), gateway message
parsing, future MCP integration. After this, every LLM call can return typed data.

## Boundaries

- Do NOT touch gateway/, cli.py, or memory/store.py
- Do NOT add structlog — keep stdlib logging
- Do NOT change how agent.py calls query() for the main agent loop (that stays text)
- Only change llm.py, search.py, add new schemas module, and tests
- Tests MUST pass: `uv run python -m pytest tests/ -v`
- Commit after each logical unit

## Background

The SDK supports `output_format={"type": "json_schema", "schema": {...}}` natively.
When set, the result comes back in `message.structured_output` (pre-parsed dict).
Pydantic v2 is already a transitive dep via `anthropic`. Combined pattern:

```python
from pydantic import BaseModel

class MySchema(BaseModel):
    title: str
    score: float

# SDK call with structured output:
options = ClaudeAgentOptions(
    model="claude-sonnet-4-20250514",
    max_turns=1,
    output_format={"type": "json_schema", "schema": MySchema.model_json_schema()},
    permission_mode="bypassPermissions",
    allowed_tools=[],
)
async for msg in query(prompt=prompt, options=options):
    if hasattr(msg, 'structured_output') and msg.structured_output:
        result = MySchema.model_validate(msg.structured_output)
    elif hasattr(msg, 'result') and msg.result:
        # fallback: try parsing result text as JSON
        result = MySchema.model_validate_json(msg.result)
```

Reference: ~/dev/claude-orchestra/src/session.ts lines 712-717 (schema passing)
and 871-893 (structured_output extraction with fallback).

## Step-by-Step

### 1. Read existing code first
- Read src/aion/llm.py (46 LOC) — current aux LLM wrapper
- Read src/aion/memory/search.py (293 LOC) — uses llm.complete() for summaries
- Read tests/test_llm.py and tests/test_search.py

### 2. Create schemas module (src/aion/schemas.py)

Define Pydantic v2 models for all structured outputs Aion needs:

```python
"""Pydantic v2 schemas for structured LLM output."""
from pydantic import BaseModel, Field
from typing import Optional

class SessionTitle(BaseModel):
    """Generated title for a conversation session."""
    title: str = Field(description="Short, descriptive title (3-8 words)")

class SessionSummary(BaseModel):
    """Summary of a past session for search results."""
    title: str = Field(description="Short title for the session")
    summary: str = Field(description="2-4 sentence summary of what was discussed/accomplished")
    relevance: float = Field(ge=0.0, le=1.0, description="Relevance to the search query, 0-1")

class SearchResult(BaseModel):
    """Container for multiple session summaries."""
    sessions: list[SessionSummary]
```

Keep it minimal — only schemas we USE right now. Add more as needed.

### 3. Update llm.py — add structured output support

Add a `complete_structured()` function alongside existing `complete()`:

```python
from pydantic import BaseModel
from typing import Type, TypeVar

T = TypeVar("T", bound=BaseModel)

async def complete_structured(
    prompt: str,
    schema: Type[T],
    system: str = "",
    model: str = "claude-sonnet-4-20250514",
) -> Optional[T]:
    """LLM call that returns a validated Pydantic model.
    
    Uses SDK's output_format for guaranteed schema compliance.
    Falls back to parsing result text if structured_output is missing.
    Returns None on error (same contract as complete()).
    """
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        result = None
        async for msg in query(
            prompt=full_prompt,
            options=ClaudeAgentOptions(
                model=model,
                max_turns=1,
                max_budget_usd=0.05,
                permission_mode="bypassPermissions",
                allowed_tools=[],
                output_format={
                    "type": "json_schema",
                    "schema": schema.model_json_schema(),
                },
            ),
        ):
            # SDK pre-parses structured output when output_format is set
            if hasattr(msg, 'structured_output') and msg.structured_output:
                result = schema.model_validate(msg.structured_output)
            elif hasattr(msg, 'result') and msg.result:
                # Fallback: parse result text as JSON
                result = schema.model_validate_json(msg.result)
        return result
    except Exception:
        logger.warning("Structured LLM call failed", exc_info=True)
        return None
```

KEEP the existing `complete()` function — it's still useful for free-form text.

### 4. Update search.py — use structured output for summaries

Current code in search.py calls `llm.complete()` with a text prompt and then
parses the free-form text response manually. Replace with `llm.complete_structured()`.

Find where search.py builds summaries and replace the pattern:
- OLD: `result = await complete(prompt)` → manually parse text
- NEW: `result = await complete_structured(prompt, SessionSummary)` → typed result

Read the full search.py first. The key functions to update are the ones that
call `complete()` for summarization. The FTS5 search logic stays unchanged.

Also update title generation (if search.py generates session titles) to use
`complete_structured(prompt, SessionTitle)`.

### 5. Update __init__.py exports

Add schemas to package exports:
```python
from .schemas import SessionTitle, SessionSummary, SearchResult
from .llm import complete, complete_structured
```

### 6. Tests

Update tests/test_llm.py:
- Test complete_structured() with a mock that returns structured_output
- Test complete_structured() fallback when structured_output is None but result is JSON
- Test complete_structured() returns None on invalid JSON
- Test complete_structured() returns None on schema validation failure
- Test that complete() (old function) still works unchanged

Add tests/test_schemas.py:
- Test each schema validates correctly
- Test each schema rejects bad data (missing fields, wrong types)
- Test model_json_schema() produces valid JSON schema

Update tests/test_search.py:
- Update mocks to return structured output instead of free text
- Verify search results come back as proper typed objects

## Verification

1. `uv run python -m pytest tests/ -v` — all tests pass (old + new)
2. `uv run python -c "from aion.schemas import SessionSummary; print(SessionSummary.model_json_schema())"` works
3. No unused imports, no debug prints
4. Each commit is atomic with descriptive message
