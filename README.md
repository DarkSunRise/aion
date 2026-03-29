# Aion

Enterprise-hardened AI agent built on Anthropic's Claude Agent SDK.

**Subscription-native. Memory-aware. Gateway-first.**

Aion wraps `claude-agent-sdk` with persistent cross-session memory, multi-platform messaging (Telegram, Discord, Slack, etc.), and enterprise features (secret redaction, session search, audit safety).

## Quick Start

```bash
# Install
uv sync

# Set your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# CLI mode
uv run aion "write a haiku about coding"

# Interactive REPL
uv run aion

# Start Telegram gateway
TELEGRAM_BOT_TOKEN=... uv run aion --gateway telegram
```

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

**What Aion adds on top of the Agent SDK:**
- **Persistent memory** — bounded curated memory (MEMORY.md + USER.md) injected into system prompt, survives across sessions
- **Session persistence** — SQLite + FTS5 full-text search across all past conversations
- **Multi-platform gateway** — Telegram, Discord, Slack, WhatsApp, Signal, email, SMS, webhook, API
- **Enterprise hardening** — secret redaction (13 patterns), memory injection scanning, audit safety
- **LLM-powered search** — natural language search across past sessions via auxiliary LLM

**What Aion does NOT do:**
- No custom agent loop (Claude Agent SDK handles it)
- No custom tool implementations (CC CLI has Read/Write/Edit/Bash/etc.)
- No prompt caching logic (CC CLI handles it)
- No context compression (CC CLI handles it)

## Memory System

Two bounded stores, injected into every session:

| Store | File | Limit | Purpose |
|-------|------|-------|---------|
| Memory | `~/.aion/memories/MEMORY.md` | 2,200 chars | Agent's notes: env facts, project conventions, tool quirks |
| User | `~/.aion/memories/USER.md` | 1,375 chars | User profile: preferences, communication style, corrections |

## Configuration

```yaml
# ~/.aion/config.yaml
model: claude-sonnet-4-20250514
max_turns: 100
permission_mode: bypassPermissions

memory:
  char_limit: 2200
  user_char_limit: 1375

gateway:
  telegram:
    bot_token: ${TELEGRAM_BOT_TOKEN}

auxiliary:
  provider: google
  model: gemini-2.0-flash
  api_key: ${GOOGLE_API_KEY}
```

## Tests

77 tests covering memory store, sessions (thread safety, migrations, FTS5, WAL), search, redaction, config, and CLI.

```bash
uv run pytest tests/ -v
```

## License

MIT
