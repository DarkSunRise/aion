# Kode — Development Guide

## What This Is

Enterprise-hardened AI agent built on Anthropic's `claude-agent-sdk` (Python).
Thin orchestration shell: memory + gateway + session tracking on top of CC SDK.

## Architecture

```
src/kode/
├── agent.py           # Core: wraps claude-agent-sdk query() with memory injection
├── config.py          # Config loader (YAML + env interpolation)
├── cli.py             # CLI entry point (one-shot + interactive)
├── redact.py          # Secret redaction for audit safety
├── memory/
│   ├── store.py       # MemoryStore: bounded MEMORY.md + USER.md (from Hermes)
│   └── sessions.py    # SessionDB: SQLite + FTS5 cross-session search
├── gateway/
│   ├── adapters/      # Platform adapters (telegram, discord, slack, etc.)
│   └── __init__.py
└── tools/             # Optional MCP tools (TTS, image-gen, etc.)
```

## Key Design Decisions

1. **Claude Agent SDK is the brain** — we don't implement an agent loop, tools, context
   compression, or prompt caching. CC SDK does all of that.

2. **Memory is injected via append_system_prompt** — frozen snapshot at session start,
   writes update disk immediately but don't break prompt cache.

3. **Sessions track CC session IDs** — enables resume across Kode restarts.

4. **Anthropic-first** — optional Gemini for cheap vision/summarization via auxiliary config.

## Dev Commands

```bash
uv sync                          # Install deps
uv run python -m kode.cli "test" # Run one-shot
uv run pytest tests/             # Run tests
```

## Adding a Gateway Adapter

1. Create `src/kode/gateway/adapters/<platform>.py`
2. Implement async message receive → agent.run() → send response
3. Register in gateway runner

## Adding an MCP Tool

For tools not in CC (TTS, image gen, etc.), create an MCP server:
1. Create `src/kode/tools/<name>.py` using `claude_agent_sdk.tool()` or standalone MCP
2. Register in config.yaml under `mcp_servers`
