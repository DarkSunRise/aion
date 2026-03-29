# Memory System Port — Hermes → Aion

## Goal

Port Hermes's battle-tested memory infrastructure into Aion. When done:
1. `sessions.py` is hardened (thread safety, write contention, FTS5 sanitization, schema migrations, richer fields)
2. New `src/aion/llm.py` provides auxiliary LLM calls via the same claude-agent-sdk
3. New `src/aion/memory/search.py` provides LLM-powered session search
4. All new code has tests
5. All 16 existing tests still pass

## Architecture Constraint

Aion wraps `claude-agent-sdk`. ALL LLM calls — main agent AND auxiliary — go through `claude_agent_sdk.query()`. The SDK handles auth via the user's existing `claude` CLI login. No API key needed. One path.

For auxiliary calls (search summaries, title gen), use the same SDK with constrained options:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async def complete(prompt: str, system: str = "") -> Optional[str]:
    """Lightweight LLM call via claude-agent-sdk — no tools, 1 turn, tiny budget."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    result_text = None
    async for msg in query(
        prompt=full_prompt,
        options=ClaudeAgentOptions(
            model="claude-sonnet-4-20250514",
            max_turns=1,
            max_budget_usd=0.05,
            permission_mode="bypassPermissions",
        ),
    ):
        if hasattr(msg, "result"):
            result_text = msg.result
    return result_text
```

**Context compression is NOT needed** — the SDK handles its own context compaction automatically (emits `compact_boundary` system messages). We do NOT port Hermes's ContextCompressor. The SDK is the brain; we don't second-guess it.

## Reference: Hermes Source Files

Read these files as reference before implementing. They are the battle-tested originals:
- `/home/kostya/dev/hermes-agent/hermes_state.py` (1274 LOC) — SQLite state store
- `/home/kostya/dev/hermes-agent/tools/session_search_tool.py` (497 LOC) — LLM search

Also reference claude-orchestra's patterns:
- `/tmp/orchestra-patterns.md` — how orchestra uses query() for lightweight calls

Do NOT copy Hermes files verbatim — adapt to Aion's architecture (constructor params, no hermes_constants, no tool registry).

## Boundaries

- Do NOT modify `src/aion/agent.py` — that's a separate task
- Do NOT modify `src/aion/memory/store.py` — it's nearly complete
- Do NOT add new deps to pyproject.toml — claude-agent-sdk is sufficient
- Do NOT implement gateway adapters — separate task
- Do NOT implement a context compressor — the SDK handles compaction
- All imports must use `from aion.` not `from hermes_`
- Keep Aion's constructor-param pattern (no hardcoded paths, no singletons)

## Step-by-Step

### Commit 1: `src/aion/llm.py` — Auxiliary LLM via SDK

Create a thin module for lightweight LLM calls. All calls go through `claude_agent_sdk.query()` with constrained options (no tools, 1 turn, small budget).

Implement:
- `async def complete(prompt: str, system: str = "", model: str = "claude-sonnet-4-20250514", max_tokens: int = 1024) -> Optional[str]`
  Uses `query()` with `max_turns=1`, `max_budget_usd=0.05`, `permission_mode="bypassPermissions"`. Iterates the async response, extracts `result` from ResultMessage.
  On error, logs warning and returns None.

Test: `tests/test_llm.py` — mock `claude_agent_sdk.query` to return a fake ResultMessage, verify complete() extracts text. Test error handling returns None.

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
5. Summarize each session via `aion.llm.complete()` — uses SDK query() under the hood
6. Exclude current_session_id from results
7. Walk parent_session_id chains to find root sessions

Use `aion.llm.complete()` for summaries. System prompt for summarization should ask for a focused summary of what was discussed/decided relevant to the search query.

Test: `tests/test_search.py` — search with mock LLM, recent sessions mode, parent chain resolution.

### Commit 4: Wire up and final tests

- Update `src/aion/memory/__init__.py` to re-export MemoryStore, SessionDB, search_sessions
- Create `src/aion/agent/__init__.py` if needed
- Run full test suite: `uv run pytest tests/ -v`
- Ensure all 16 original tests + all new tests pass

## Validation

After each commit:
```bash
uv run pytest tests/ -v
```

All tests must pass before moving to next commit. If a test fails, fix it before committing.
