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
└── tools/             # MCP tools (TODO)
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

## Adding an MCP Tool

For tools not in CC (TTS, image gen, etc.), create an MCP server:
1. Create `src/aion/tools/<name>.py` using `claude_agent_sdk.tool()` or standalone MCP
2. Register in config.yaml under `mcp_servers`
