# Agent Improvements — Full SDK Integration

## Goal
Make agent.py handle all SDK message types properly, use system_prompt preset, track compaction events, and support session continuation within a REPL.

## Current State
Read `src/aion/agent.py` (174 LOC) — wraps query() but only handles basic message types.
Read `src/aion/config.py` — has AionConfig with model, max_turns, permission_mode.
Read `src/aion/memory/sessions.py` — has hardened session store.
Also read `/tmp/orchestra-patterns.md` — see how orchestra uses query() options.

The Python SDK's query() returns async iterator of: UserMessage, AssistantMessage, SystemMessage, ResultMessage, StreamEvent, RateLimitEvent.

Key SDK options to use (from ClaudeAgentOptions):
- `system_prompt` can be string or `{"type": "preset", "preset": "claude_code", "append": memory_block}`
- `resume` for session resumption (string session_id)  
- `continue_conversation` for continuing within same process
- `model`, `max_turns`, `max_budget_usd`, `permission_mode`
- `cwd`, `env`, `effort`

## Boundaries
- Do NOT modify sessions.py, store.py, llm.py, search.py, or cli.py
- Do NOT add new dependencies
- Keep agent.py focused — orchestration layer, not business logic

## Tasks (1 commit)

### 1. Use system_prompt preset instead of append_system_prompt
Change from `append_system_prompt=memory_block` to:
```python
system_prompt={
    "type": "preset",
    "preset": "claude_code", 
    "append": memory_block,
}
```
This gives the agent CC's full system prompt PLUS our memory injection.

### 2. Handle all message types in the stream
Expand `_message_to_dict()` to handle:
- `SystemMessage` — extract session_id from init, detect `compact_boundary` subtype
- `AssistantMessage` — already handled, but add thinking block support
- `UserMessage` — tool results
- `ResultMessage` — already handled, but extract `total_cost_usd`, `duration_api_ms`, `stop_reason`, `num_turns`
- `StreamEvent` — pass through for streaming display
- `RateLimitEvent` — log rate limit info

### 3. Track compaction events
When a system message with subtype `compact_boundary` arrives, log it and optionally create a child session in the DB (parent_session_id linkage).

### 4. Session continuation support
Add a `continue_session()` method that reuses the last CC session_id:
```python
async def continue_session(self, prompt: str, cc_session_id: str, **kwargs) -> AsyncIterator[dict]:
    """Continue an existing CC session."""
    # Uses resume=cc_session_id in options
```

### 5. Better token tracking
Extract from ResultMessage: `total_cost_usd`, `usage` dict (input_tokens, output_tokens, cache_read, cache_write), and store in session DB via `end_session()`.

### 6. Add model override support
Accept optional `model` param in `run()` that overrides config.model.

Test: `tests/test_agent.py` — mock claude_agent_sdk.query, verify message type handling, verify system_prompt format, verify session continuation flow.

Run `uv run python -m pytest tests/ -v` after changes to verify all tests pass.
