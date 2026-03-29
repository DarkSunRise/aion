# Aion — Handover & Roadmap

> Last updated: 2026-03-29
> Version: 0.3.0 | 3,814 LOC source | 258 tests passing
> Relationship: Extends Hermes (Python) — modernized brain (claude-agent-sdk) for Hermes body (gateway, skills, cron)
> Repo: https://github.com/DarkSunRise/aion

## What Aion Is

Subscription-native AI agent built on `claude-agent-sdk` (Python). Thin orchestration shell: memory + gateway + session tracking on top of Claude Code SDK. Uses the user's existing `claude` CLI auth — no API key needed. ALL LLM calls (main agent AND auxiliary) go through `sdk.query()`.

## What Exists (v0.3.0)

```
src/aion/                    3,814 LOC
├── __init__.py              version 0.3.0, exports AionAgent/AionConfig
├── agent.py           ~400  wraps query() — system_prompt preset, all msg types,
│                            compaction tracking, session continuation, token tracking,
│                            SDK hooks, external MCP server support
├── cli.py             ~300  argparse — one-shot, REPL, --resume/--continue/--model/
│                            --sessions/--search, --gateway, /commands in REPL
├── config.py          ~150  dataclasses + YAML + ${ENV} interpolation + mcp_servers
├── hooks.py           ~120  SDK lifecycle hooks (Stop, Notification, PreCompact,
│                            PreToolUse, PostToolUse, Subagent*) + gateway notify callback
├── log.py              ~60  structlog config — JSON in gateway, colored in CLI
├── llm.py              ~90  aux LLM via query() — sonnet + complete_structured() + Pydantic
├── schemas.py          ~30  Pydantic v2 models — SessionTitle, SessionSummary, SearchResult
├── redact.py           ~43  13 compiled regex patterns for secret redaction
├── utils/
│   └── ansi.py         ~50  strip ANSI escape codes from CC output
├── memory/
│   ├── store.py       293   bounded MEMORY.md + USER.md, fcntl locking, injection scan
│   ├── sessions.py    767   SQLite+FTS5, thread-safe, write contention retry, WAL
│   └── search.py      ~300  LLM-powered session search via complete_structured()
├── gateway/
│   ├── base.py        ~120  abstract GatewayAdapter + GatewayMessage
│   ├── config.py      ~100  GatewayConfig, TelegramConfig, SlackConfig + allowlists
│   ├── runner.py      ~250  adapter lifecycle, message→agent→response, signal handling
│   ├── session.py     ~140  SessionSource, context prompt builder, SessionTracker (30min continuity)
│   └── adapters/
│       ├── telegram.py ~200 python-telegram-bot v20+ polling, /start, /new, allowlist
│       └── slack.py    ~220 slack-bolt Socket Mode, thread replies, mention detection
└── tools/
    ├── mcp_tools.py   ~200  7 in-process MCP tools (memory CRUD + session list/search/messages)
    └── server.py       ~30  create_aion_mcp_server() factory

tests/                     258 passing
deps: claude-agent-sdk, anthropic, aiohttp, python-telegram-bot, slack-bolt, slack-sdk,
      pyyaml, structlog, pydantic
```

## Architecture Decisions (locked in)

1. **SDK is the brain** — no custom agent loop, no tool registry, no context compressor
2. **SDK handles compaction** — we listen for `compact_boundary` system messages, don't second-guess
3. **Memory injected via system_prompt preset** — `{type: "preset", preset: "claude_code", append: memory_block}`
4. **Auxiliary LLM = same query()** — sonnet, `max_turns=1`, no tools, tiny budget
5. **Raw sqlite3** — 767 LOC is battle-hardened, ORMs don't help
6. **Adapter pattern for gateway** — per-platform adapters behind a base class

## Library Decisions (from research)

| Decision | Library | Why |
|----------|---------|-----|
| **ADOPT** | structlog | Structured logging. JSON in prod, colored in dev. 100KB pure Python. |
| **ADOPT** | pydantic v2 | Already transitive via anthropic. Use for structured output schemas. |
| **ADOPT** | mcp SDK | MCP Python SDK. Aligns with orchestra + Oro. |
| **KEEP** | python-telegram-bot | Primary gateway. Already a dep. |
| **KEEP** | raw sqlite3 | Hand-rolled sessions.py is better than any ORM for our use case. |
| **KEEP** | argparse | Switch to typer when CLI exceeds 15 flags. |
| **KEEP** | asyncio | SDK-native, no cross-loop needs. |
| **DROP** | google-genai optional | We don't need Gemini — SDK handles everything. |
| **SKIP** | discord.py, matrix-nio | Not needed now. |
| **SKIP** | LangChain, CrewAI, etc | SDK provides everything. |

## Structured Output Pattern

SDK has native `output_format`. Combined with Pydantic:

```python
from pydantic import BaseModel
from claude_agent_sdk import query, ClaudeAgentOptions

class SearchSummary(BaseModel):
    title: str
    summary: str
    relevance: float

options = ClaudeAgentOptions(
    model="claude-sonnet-4-20250514",
    max_turns=1,
    output_format={"type": "json_schema", "schema": SearchSummary.model_json_schema()},
    permission_mode="bypassPermissions",
)
# Result in msg.structured_output → SearchSummary.model_validate_json(...)
```

## Reference Repos

| Repo | Path | What to steal |
|------|------|---------------|
| Hermes | ~/.hermes/hermes-agent | Python. Gateway (13 platforms), memory (bounded md + SQLite+FTS5), skills, cron, tools, context compression. Aion's upstream — we extend/fork it, not replace it. |
| claude-orchestra | ~/dev/claude-orchestra | SDK patterns, structured output, context management |
| Oro | ~/dev/awo/packages/oro | Orchestration patterns, job queue design |

Full analysis docs at `docs/analysis/`:
- `hermes-inventory.md` — 67K LOC component inventory with portability tiers
- `memory-comparison.md` — gap analysis: what Aion is missing vs Hermes memory
- `orchestra-patterns.md` — SDK usage patterns (5 query() variants)
- `aion-infra-libs-research.md` — infrastructure library verdicts
- `aion-integration-libs-research.md` — integration library verdicts

---

## SDK Surface (key types for implementation)

The SDK is richer than it looks. Key exports for upcoming phases:

**Hooks** (WIRED in hooks.py):
- Stop, Notification, PreCompact, PreToolUse, PostToolUse, SubagentStart, SubagentStop
- Gateway notify callback for forwarding notifications to users
- Fail-safe: falls back to no hooks if SDK raises on signature mismatch

**Session management** (SDK-native — augments our SQLite):
- `list_sessions`, `get_session_messages`, `get_session_info`
- `fork_session`, `delete_session`, `rename_session`, `tag_session`

**MCP** (SDK-native passthrough):
- `McpSdkServerConfig`, `create_sdk_mcp_server`
- Pass `mcp_servers=[]` to `ClaudeAgentOptions`

---

## Roadmap

### Done (v0.3.0)

| Phase | Task | Status |
|-------|------|--------|
| 0.0 | Structured output — Pydantic schemas, complete_structured(), typed search | ✅ |
| 0.1 | Telegram + Slack gateway — adapters, runner, CLI --gateway, ANSI strip | ✅ |
| 0.2 | MCP tools — 7 in-process tools (memory CRUD + sessions) | ✅ |
| 1.1 | structlog — JSON in gateway, colored in CLI, log.py | ✅ |
| 1.3 | SDK hooks — 7 lifecycle hooks + gateway notify callback | ✅ |
| 2.1 | MCP client — external servers via config.yaml | ✅ |
| 2.2 | MCP server — Aion memory/search as MCP tools | ✅ |
| 3.1 | Slack adapter — slack-bolt Socket Mode | ✅ |
| — | Gateway session continuity — 30min window, /new command | ✅ |

### Remaining (needs dogfood validation)

| # | Task | Notes |
|---|------|-------|
| D.1 | **Dogfood** — actually run `aion --gateway telegram` with real bot token | Highest priority — real usage reveals real bugs |
| D.2 | **Streaming display** — show progress in CLI/gateway (typing indicators) | Quality of life for gateway users |
| D.3 | **delegate_task** — subagent spawning via SDK | Uses SubagentStart/Stop hooks already wired |
| D.4 | **PermissionRequest hook** — handle permission prompts in gateway | Currently only works in CLI mode |
| D.5 | **Context compression evaluation** — test SDK compaction vs Hermes's 676-LOC compressor | May need Hermes's compressor for long sessions |

---

## How to Use This Handover

This document is the entry point for any agent working on Aion. When starting a session:

1. Read this file first
2. Read CLAUDE.md for dev conventions
3. Read the specific phase/task you're working on
4. Check `docs/analysis/` for reference material if needed
5. Run `uv run python -m pytest tests/ -v` before and after changes

For spawning CC agents on Aion tasks, use the session prompt pattern:
```
claude --dangerously-skip-permissions -p 'Read docs/HANDOVER.md for project context.
Then implement Phase X.Y: [task description]. Read all referenced source files first.
Do NOT stop to ask questions. Commit when done.'
```

## Key Constraints

- Python >=3.11, uv + hatchling
- All LLM calls through claude-agent-sdk query() — subscription-native
- No API keys required for any core functionality
- Tests must pass after every change: `uv run python -m pytest tests/ -v`
- Commit after each logical unit
