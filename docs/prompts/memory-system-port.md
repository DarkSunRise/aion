# Memory System Port — Hermes → Aion

## Goal

Port Hermes's battle-tested memory infrastructure into Aion. When done:
1. `sessions.py` is hardened (thread safety, write contention, FTS5 sanitization, schema migrations, richer fields)
2. New `src/aion/llm.py` provides optional Anthropic API client for auxiliary LLM calls
3. New `src/aion/memory/search.py` provides LLM-powered session search
4. New `src/aion/agent/compressor.py` provides context compression
5. All new code has tests
6. All 16 existing tests still pass

## Architecture Constraint

Aion wraps `claude-agent-sdk` — Claude Code is the brain. The `anthropic` library is a TRANSITIVE dep (already installed via claude-agent-sdk). We use it OPTIONALLY for lightweight auxiliary calls:
- Session search summarization (haiku)
- Context compression summaries (haiku)  
- Title generation (haiku)

If no `ANTHROPIC_API_KEY` is set, these features degrade gracefully (no summaries, no compression, raw FTS results only).

## Reference: Hermes Source Files

Read these files as reference before implementing. They are the battle-tested originals:
- `/home/kostya/dev/hermes-agent/hermes_state.py` (1274 LOC) — SQLite state store
- `/home/kostya/dev/hermes-agent/tools/session_search_tool.py` (497 LOC) — LLM search
- `/home/kostya/dev/hermes-agent/agent/context_compressor.py` (676 LOC) — compression

Do NOT copy them verbatim — adapt to Aion's architecture (constructor params, no hermes_constants, no tool registry).

## Boundaries

- Do NOT modify `src/aion/agent.py` — that's a separate task
- Do NOT modify `src/aion/memory/store.py` — it's nearly complete (only add fsync if trivial)
- Do NOT add new deps to pyproject.toml — `anthropic` is already available transitively
- Do NOT implement gateway adapters — separate task
- All imports must use `from aion.` not `from hermes_`
- Keep Aion's constructor-param pattern (no hardcoded paths, no singletons)

## Step-by-Step

### Commit 1: `src/aion/llm.py` — Optional Anthropic Client

Create a thin wrapper:

```python
"""Optional Anthropic API client for auxiliary LLM calls.

Used for: session search summaries, context compression, title generation.
Falls back gracefully when ANTHROPIC_API_KEY is not set.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_client = None
_checked = False

def get_client():
    """Get anthropic.Anthropic client, or None if no API key."""
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY not set — auxiliary LLM features disabled")
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
        return _client
    except Exception as e:
        logger.warning("Failed to create Anthropic client: %s", e)
        return None

def complete(prompt: str, system: str = "", model: str = "claude-haiku-4-20250514",
             max_tokens: int = 1024) -> Optional[str]:
    """Simple completion. Returns None if client unavailable."""
    client = get_client()
    if not client:
        return None
    try:
        messages = [{"role": "user", "content": prompt}]
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, messages=messages,
            system=system if system else anthropic.NOT_GIVEN,
        )
        return resp.content[0].text if resp.content else None
    except Exception as e:
        logger.warning("LLM completion failed: %s", e)
        return None
```

Test: `tests/test_llm.py` — test graceful None when no key, mock successful call.

### Commit 2: Harden `src/aion/memory/sessions.py`

Read `/home/kostya/dev/hermes-agent/hermes_state.py` carefully. Port these features:

**Thread safety:**
- Add `threading.Lock` wrapping all DB operations
- Add `_execute_write()` method with BEGIN IMMEDIATE + jitter retry (15 attempts)

**Schema upgrades:**
- Bump to SCHEMA_VERSION = 2
- Add migration system: `_run_migrations()` that checks current version and applies ALTER TABLEs
- New columns on sessions: `parent_session_id TEXT REFERENCES sessions(id)`, `end_reason TEXT`, `tool_call_count INTEGER DEFAULT 0`, `cache_read_tokens INTEGER DEFAULT 0`, `cache_write_tokens INTEGER DEFAULT 0`, `reasoning_tokens INTEGER DEFAULT 0`
- New columns on messages: `tool_call_id TEXT`, `tool_calls TEXT` (JSON), `finish_reason TEXT`, `reasoning TEXT`
- UNIQUE INDEX on sessions(title) WHERE title IS NOT NULL

**FTS5 hardening:**
- Port `_sanitize_fts5_query()` from hermes_state.py (handles quotes, operators, hyphens, wildcards)
- Use `snippet()` in search results

**WAL management:**
- `_try_wal_checkpoint()` on close
- Periodic checkpoint hint

**Additional methods to port:**
- `get_messages_as_conversation()` — reconstruct OpenAI-format messages with tool_calls
- `list_sessions_rich()` — single-query rich listing with preview, last_active
- `resolve_session_id()` — prefix resolution
- `set_session_title()` with sanitization and uniqueness
- `session_count()`

Keep existing API backward-compatible — don't break create_session, end_session, add_message, search, recent_sessions, get_session_messages, get_cc_session_id.

Test: `tests/test_sessions.py` — thread safety (concurrent writes), FTS5 sanitization (special chars), migration (v1→v2), rich listing, title management.

### Commit 3: `src/aion/memory/search.py` — LLM-Powered Session Search

Port from `/home/kostya/dev/hermes-agent/tools/session_search_tool.py`. Simplified version:

Core function: `async def search_sessions(db: SessionDB, query: str, limit: int = 3, current_session_id: str = None) -> str`

Flow:
1. If no query → recent sessions mode (no LLM, just formatted list)
2. Sanitize query via `db._sanitize_fts5_query()`
3. FTS5 search → get matching sessions
4. For each session, get messages, truncate around matches (100K char window)
5. If LLM available (`llm.get_client()`): summarize each session in parallel with asyncio
6. If no LLM: return raw matches with snippets (graceful degradation)
7. Exclude current_session_id from results
8. Walk parent_session_id chains to find root sessions

Use `aion.llm.complete()` for summaries. System prompt for summarization should ask for a focused summary of what was discussed/decided relevant to the search query.

Test: `tests/test_search.py` — search with mock LLM, search without LLM (degraded), recent sessions mode.

### Commit 4: `src/aion/agent/compressor.py` — Context Compression

Port from `/home/kostya/dev/hermes-agent/agent/context_compressor.py`. Key features:

```python
class ContextCompressor:
    def __init__(self, model: str, context_window: int, threshold: float = 0.7):
        """
        Args:
            model: model name (for token estimation)
            context_window: max context tokens
            threshold: compress when usage > threshold (0.7 = 70%)
        """
    
    def should_compress(self, current_tokens: int) -> bool: ...
    def compress(self, messages: list, current_tokens: int = None) -> list: ...
```

Port these from Hermes:
- Head/tail protection (keep first N + last M messages)
- Token-budget tail protection (scale with context window)
- Tool output pruning pre-pass (cheap, no LLM)
- Structured summary generation via `aion.llm.complete()`
- Tool call/result pair sanitization (never orphan a tool_call without result)
- Boundary alignment (don't split tool_call/result groups)
- Graceful degradation: if no LLM, just do tool output pruning + aggressive tail keeping

If `aion.llm.complete()` returns None (no API key), skip LLM summary and fall back to mechanical pruning only.

Test: `tests/test_compressor.py` — compression triggers, head/tail protection, tool pair sanitization, no-LLM fallback.

### Commit 5: Wire up and final tests

- Update `src/aion/memory/__init__.py` to re-export MemoryStore, SessionDB, search_sessions
- Update `src/aion/agent/__init__.py` (create if needed)  
- Add `src/aion/agent/compressor.py` to `__init__.py`
- Run full test suite: `uv run pytest tests/ -v`
- Ensure all 16 original tests + all new tests pass

## Validation

After each commit:
```bash
uv run pytest tests/ -v
```

All tests must pass before moving to next commit. If a test fails, fix it before committing.
