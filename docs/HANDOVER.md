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

## Roadmap

### Phase 1: Foundation Polish (self-iteration ready)

| # | Task | Files | Est. LOC | Deps |
|---|------|-------|----------|------|
| 1.1 | **structlog integration** — replace stdlib logging across all modules. JSON output in gateway mode, colored dev output in CLI. Add structlog to deps. | all *.py | ~50 changed | structlog |
| 1.2 | **Structured output support** — add `output_format` to agent.py, add Pydantic schemas for auxiliary calls (search summaries, titles). Update llm.py to use structured output. | agent.py, llm.py, new schemas.py | ~100 new | pydantic (transitive) |
| 1.3 | **pyproject.toml cleanup** — add structlog+mcp to core deps, drop gemini optional, add slack optional extra. | pyproject.toml | ~10 | — |

### Phase 2: Telegram Gateway

| # | Task | Files | Est. LOC | Reference |
|---|------|-------|----------|-----------|
| 2.1 | **Gateway base class** — abstract adapter with normalize_message/send_response/start/stop. Port from Hermes `gateway/platforms/base.py` (1452 LOC) — simplify heavily (Aion doesn't need half of it). | gateway/base.py | ~300 | hermes base.py |
| 2.2 | **Gateway config** — platform configs, allowlists, session routing. | gateway/config.py | ~150 | hermes gateway/config.py |
| 2.3 | **Telegram adapter** — port from Hermes (1906 LOC). Message receive → agent.run() → send response. Voice, stickers, documents. | gateway/adapters/telegram.py | ~500 | hermes telegram.py |
| 2.4 | **Gateway runner** — parse config, start adapters as asyncio tasks, graceful shutdown. Wire into CLI `aion --gateway`. | gateway/runner.py, cli.py | ~200 | new |
| 2.5 | **ANSI stripping** — strip escape codes from CC output before sending to Telegram. | utils/ansi.py | ~50 | hermes ansi_strip.py |

### Phase 3: Hooks & Async Notifications

| # | Task | Files | Est. LOC |
|---|------|-------|----------|
| 3.1 | **SDK hooks wiring** — use ClaudeAgentOptions.hooks for Stop, Notification, PreCompact, RateLimitEvent. Emit asyncio.Event on completion. | agent.py | ~80 |
| 3.2 | **Completion callbacks** — register callbacks for session completion. Gateway adapters subscribe to get notified instead of polling. | agent.py, gateway/base.py | ~60 |
| 3.3 | **Rate limit handling** — on RateLimitEvent, backoff and notify user on gateway. | agent.py | ~40 |

### Phase 4: MCP Integration

| # | Task | Files | Est. LOC |
|---|------|-------|----------|
| 4.1 | **MCP client** — connect to external MCP servers defined in config.yaml. Pass to SDK via `mcp_servers` option. | tools/mcp_bridge.py, config.py | ~150 |
| 4.2 | **MCP server** — expose Aion's memory/search as MCP tools for other agents. | tools/mcp_server.py | ~100 |

### Phase 5: Slack Gateway (optional)

| # | Task | Files | Est. LOC |
|---|------|-------|----------|
| 5.1 | **Slack adapter** — slack-bolt based. Socket Mode + webhook. | gateway/adapters/slack.py | ~300 |

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
