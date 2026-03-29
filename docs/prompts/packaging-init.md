# Packaging & Init — Make Aion Importable

## Goal
Clean up package exports, add version, write CLAUDE.md that reflects current architecture.

## Current State
Read `src/aion/__init__.py` — empty.
Read `src/aion/memory/__init__.py` — has re-exports.
Read `pyproject.toml` — version 0.1.0.
Read `CLAUDE.md` — outdated (references old architecture).
Read `README.md` — outdated.

## Boundaries
- Do NOT modify agent.py, cli.py, sessions.py, store.py, llm.py, search.py
- Do NOT add new dependencies
- Do NOT change any test files

## Tasks (1 commit)

### 1. `src/aion/__init__.py`
Export version and key classes:
```python
"""Aion — subscription-native AI agent on claude-agent-sdk."""
__version__ = "0.2.0"

from .agent import AionAgent
from .config import AionConfig, load_config
```

### 2. Bump version in `pyproject.toml` to 0.2.0

### 3. Update `CLAUDE.md` to reflect current architecture:
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

Key design decisions:
1. ALL LLM calls go through claude-agent-sdk query() — subscription-native
2. Memory injected via system_prompt preset append — frozen snapshot at session start
3. No context compressor — SDK handles compaction automatically
4. Sessions hardened: thread safety, write contention, FTS5 sanitization, schema migrations

### 4. Update `README.md` — quick start, current architecture, 77 tests passing

Run `uv run python -m pytest tests/ -v` after changes to verify nothing broke.
