# Aion

Enterprise-hardened AI agent built on Anthropic's Claude Agent SDK.

**Anthropic-native. Gateway-first. Memory-aware.**

Aion wraps `claude-agent-sdk` with persistent cross-session memory, multi-platform messaging (Telegram, Discord, Slack, etc.), and enterprise features (audit logging, rate limiting, secret redaction).

## Architecture

```
User (Telegram/Discord/Slack/CLI)
  ↓
Gateway (message routing, auth, delivery)
  ↓
Orchestrator (memory injection, session tracking, tool config)
  ↓
claude-agent-sdk (Claude Agent SDK — subprocess to CC CLI)
  ↓
Claude Code (tools: Read, Write, Edit, Bash, MCP, skills, agents)
```

**What Aion adds on top of the Agent SDK:**
- **Persistent memory** — bounded curated memory (MEMORY.md + USER.md) injected into system prompt, survives across sessions. Ported from Hermes.
- **Session persistence** — SQLite + FTS5 full-text search across ALL past conversations (cross-platform).
- **Multi-platform gateway** — Telegram, Discord, Slack, WhatsApp, Signal, email, SMS, webhook, API.
- **Enterprise hardening** — audit logging, secret redaction, memory injection scanning, rate limiting.
- **Optional providers** — Gemini Flash for vision/cheap tasks, future extensibility.

**What Aion does NOT do:**
- No custom agent loop (Claude Agent SDK handles it)
- No custom tool implementations (CC CLI has Read/Write/Edit/Bash/etc.)
- No prompt caching logic (CC CLI handles it)
- No context compression (CC CLI handles it)

## Quick Start

```bash
# Install
uv sync

# Set your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# CLI mode
uv run aion "write a haiku about coding"

# Start Telegram gateway
TELEGRAM_BOT_TOKEN=... uv run aion --gateway telegram
```

## Memory System

Two bounded stores, injected into every session:

| Store | File | Limit | Purpose |
|-------|------|-------|---------|
| Memory | `~/.aion/memories/MEMORY.md` | 2,200 chars | Agent's notes: env facts, project conventions, tool quirks |
| User | `~/.aion/memories/USER.md` | 1,375 chars | User profile: preferences, communication style, corrections |

Memory is curated by the agent itself — it decides what's worth remembering. Entries are bounded (not infinite), forcing the agent to prioritize. Injection/exfiltration scanning prevents prompt attacks via memory.

## Session Search

All conversations are stored in SQLite with FTS5 full-text search. The agent can search its own past conversations to recall context from previous sessions — no re-explaining needed.

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
  discord:
    bot_token: ${DISCORD_BOT_TOKEN}

# Optional: Gemini for cheap vision/summarization
auxiliary:
  provider: google
  model: gemini-2.0-flash
  api_key: ${GOOGLE_API_KEY}
```

## License

MIT
