# Aion — Development Guide

## What This Is

Enterprise-hardened AI agent built on Anthropic's `claude-agent-sdk` (Python).
Thin orchestration shell: memory + gateway + session tracking on top of CC SDK.

## Architecture

```
src/aion/
├── __init__.py        # Package root, version, exports
├── agent.py           # Core: wraps claude-agent-sdk query() with memory injection
├── cli.py             # CLI: one-shot, interactive REPL, session management
├── config.py          # Config: YAML + env interpolation
├── llm.py             # Auxiliary LLM: query() with sonnet, 1 turn, no tools
├── redact.py          # Secret redaction (13 patterns)
├── memory/
│   ├── __init__.py    # Re-exports: MemoryStore, SessionDB, search_sessions
│   ├── store.py       # Bounded MEMORY.md + USER.md (from Hermes)
│   ├── sessions.py    # SQLite+FTS5: thread-safe, schema migrations, WAL
│   └── search.py      # LLM-powered session search via SDK
├── gateway/           # Platform adapters (TODO)
│   └── adapters/      # telegram, discord, etc.
└── tools/
    ├── __init__.py    # Re-exports: create_aion_tools, create_aion_mcp_server
    ├── mcp_tools.py   # @tool definitions: memory + session wrappers
    └── server.py      # create_aion_mcp_server() factory
```

## Key Design Decisions

1. **ALL LLM calls go through claude-agent-sdk query()** — subscription-native
2. **Memory injected via system_prompt preset append** — frozen snapshot at session start
3. **No context compressor** — SDK handles compaction automatically
4. **Sessions hardened** — thread safety, write contention, FTS5 sanitization, schema migrations

## Dev Commands

```bash
uv sync                          # Install deps
uv run python -m aion.cli "test" # Run one-shot
uv run pytest tests/             # Run tests
```

## Adding a Gateway Adapter

1. Create `src/aion/gateway/adapters/<platform>.py`
2. Implement async message receive → agent.run() → send response
3. Register in gateway runner

## MCP Tools (available in every Aion session)

Aion registers in-process MCP tools that give Claude persistent memory
and session history. These tools are automatically available in every session
(CLI + gateway) — no configuration needed.

- **aion_memory_read** — read persistent memory ('memory' or 'user')
- **aion_memory_add** — add entry to memory
- **aion_memory_replace** — update a memory entry (substring match)
- **aion_memory_remove** — delete a memory entry (substring match)
- **aion_sessions_list** — list recent sessions with metadata
- **aion_sessions_search** — FTS5 search across past sessions
- **aion_session_messages** — get full conversation from a session (supports prefix)

Tools are thin async wrappers around MemoryStore and SessionDB, bound via
closure in `create_aion_tools()`. The MCP server is created in AionAgent.__init__
and injected into every query()/continue_session() call.

## Adding an MCP Tool

For tools not in CC (TTS, image gen, etc.), create an MCP server:
1. Create `src/aion/tools/<name>.py` using `claude_agent_sdk.tool()` or standalone MCP
2. Register in config.yaml under `mcp_servers`
