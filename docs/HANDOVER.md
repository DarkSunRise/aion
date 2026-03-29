# Aion — Handover & Roadmap

> Last updated: 2026-03-29
> Version: 0.2.0 | 2,261 LOC source | 1,669 LOC tests | 123 passing
> Repo: https://github.com/DarkSunRise/aion

## What Aion Is

Subscription-native AI agent built on `claude-agent-sdk` (Python). Thin orchestration shell: memory + gateway + session tracking on top of Claude Code SDK. Uses the user's existing `claude` CLI auth — no API key needed. ALL LLM calls (main agent AND auxiliary) go through `sdk.query()`.

## What Exists (v0.2.0)

```
src/aion/                    2,261 LOC
├── __init__.py          5   version 0.2.0, exports AionAgent/AionConfig
├── agent.py           371   wraps query() — system_prompt preset, all msg types,
│                            compaction tracking, session continuation, token tracking
├── cli.py             293   argparse — one-shot, REPL, --resume/--continue/--model/
│                            --sessions/--search, /commands in REPL
├── config.py          143   dataclasses + YAML + ${ENV} interpolation
├── llm.py              46   auxiliary LLM via query() — sonnet, 1 turn, $0.05 budget
├── redact.py           43   13 compiled regex patterns for secret redaction
├── memory/
│   ├── store.py       293   bounded MEMORY.md + USER.md, fcntl locking, injection scan
│   ├── sessions.py    767   SQLite+FTS5, thread-safe, write contention retry,
│   │                        schema migrations v1→v2, FTS5 sanitization, WAL
│   └── search.py      293   LLM-powered session search via SDK query()
├── gateway/                 scaffolded, empty
└── tools/                   scaffolded, empty

tests/                     1,669 LOC, 123 passing
deps: claude-agent-sdk, anthropic, aiohttp, python-telegram-bot, pyyaml
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
| Hermes | ~/dev/hermes-agent | Gateway adapters (13 platforms, battle-tested) |
| claude-orchestra | ~/dev/claude-orchestra | SDK patterns, structured output, context management |
| Oro | ~/dev/awo/packages/oro | Orchestration patterns, job queue design |

Full analysis docs at `docs/analysis/`:
- `hermes-inventory.md` — 67K LOC component inventory with portability tiers
- `memory-comparison.md` — feature matrix hermes vs aion memory
- `orchestra-patterns.md` — SDK usage patterns (5 query() variants)
- `aion-infra-libs-research.md` — infrastructure library verdicts
- `aion-integration-libs-research.md` — integration library verdicts

---

## SDK Surface (key types for implementation)

The SDK is richer than it looks. Key exports for upcoming phases:

**Hooks** (ready to wire — no custom building needed):
- `StopHookInput`, `NotificationHookInput`, `PreCompactHookInput`
- `RateLimitEvent`, `PreToolUseHookInput`, `PostToolUseHookInput`
- `SubagentStartHookInput`, `SubagentStopHookInput`
- `PermissionRequestHookInput` + `PermissionResult`

**Session management** (SDK-native — augments our SQLite):
- `list_sessions`, `get_session_messages`, `get_session_info`
- `fork_session`, `delete_session`, `rename_session`, `tag_session`

**MCP** (SDK-native passthrough):
- `McpSdkServerConfig`, `create_sdk_mcp_server`
- Pass `mcp_servers=[]` to `ClaudeAgentOptions`

---

## Roadmap

### Phase 0: Dogfood (CRITICAL PATH — do this first)

Goal: talk to Aion on Telegram. Everything else is polish.

| # | Task | Files | Est. LOC | Session Prompt |
|---|------|-------|----------|----------------|
| 0.1 | **Telegram Gateway** — base class, session context, config, adapter, runner, ANSI strip, CLI wire, tests. Single CC agent session. | gateway/*, utils/ansi.py, cli.py | ~1330 new | `docs/prompts/phase2-telegram-gateway.md` |
| 0.2 | **pyproject.toml cleanup** — add structlog+mcp to core deps, drop gemini optional, add slack optional extra. | pyproject.toml | ~10 | bundled with 0.1 |

### Phase 1: Self-Iteration Polish

Only after dogfood works. Priorities reordered by what dogfood reveals.

| # | Task | Files | Est. LOC | Blocked by |
|---|------|-------|----------|------------|
| 1.1 | **structlog integration** — replace stdlib logging. JSON in gateway, colored in CLI. | all *.py | ~50 changed | nothing |
| 1.2 | **Structured output** — Pydantic schemas for aux calls (summaries, titles). | agent.py, llm.py, schemas.py | ~100 new | nothing |
| 1.3 | **SDK hooks** — wire StopHook, NotificationHook, PreCompact, RateLimit. | agent.py | ~80 | nothing |
| 1.4 | **Completion callbacks** — gateway subscribes to session events. | agent.py, gateway/base.py | ~60 | 1.3 |
| 1.5 | **Rate limit handling** — backoff + notify user on gateway. | agent.py | ~40 | 1.3 |

### Phase 2: MCP Integration

| # | Task | Files | Est. LOC |
|---|------|-------|----------|
| 2.1 | **MCP client** — connect to external MCP servers via config.yaml. Pass to SDK via `mcp_servers`. | tools/mcp_bridge.py, config.py | ~150 |
| 2.2 | **MCP server** — expose Aion's memory/search as MCP tools. | tools/mcp_server.py | ~100 |

### Phase 3: Slack Gateway (optional)

| # | Task | Files | Est. LOC |
|---|------|-------|----------|
| 3.1 | **Slack adapter** — slack-bolt, Socket Mode + webhook. | gateway/adapters/slack.py | ~300 |

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
