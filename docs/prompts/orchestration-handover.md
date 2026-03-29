# Orchestration Session Handover — Aion

Paste this after context compaction to resume the orchestration session.

## What Aion Is

Personal AI agent built on `claude-agent-sdk` (Python). Subscription-native — uses `claude` CLI auth, no API key. Thin shell: Claude Code IS the brain, Aion adds persistent memory, session tracking, and multi-platform gateways.

Repo: ~/dev/aion (DarkSunRise/aion) | v0.2.0 | 3,138 LOC | 216 tests

## What Exists (working, tested, pushed)

```
src/aion/                    3,138 LOC
├── agent.py           375   wraps SDK query(), memory injection, session tracking
│                            SDK messages: isinstance() checks (SystemMessage,
│                            AssistantMessage, ResultMessage, RateLimitEvent)
├── cli.py             305   argparse, REPL, --gateway, --resume/--continue
├── config.py          143   dataclasses + YAML + ${ENV} interpolation
├── llm.py              88   complete() + complete_structured() via SDK
├── schemas.py          27   Pydantic v2: SessionTitle, SessionSummary, SearchResult
├── redact.py           43   13 compiled regex patterns for secret redaction
├── memory/
│   ├── store.py       293   bounded MEMORY.md + USER.md, fcntl locking
│   ├── sessions.py    767   SQLite+FTS5, thread-safe, WAL, migrations
│   └── search.py      293   LLM-powered session search
├── gateway/
│   ├── base.py        116   GatewayMessage, GatewayAdapter ABC, split_message()
│   ├── session.py      77   SessionSource + build_session_context_prompt()
│   ├── config.py      101   TelegramConfig, SlackConfig, GatewayConfig
│   ├── runner.py      178   adapter lifecycle, message→agent wiring, shutdown
│   └── adapters/
│       ├── telegram.py 200  python-telegram-bot v20+ async
│       └── slack.py    216  slack-bolt Socket Mode
├── tools/
│   ├── mcp_tools.py   228  7 MCP tools (memory CRUD + session list/search/messages)
│   └── server.py       22  create_aion_mcp_server() factory
└── utils/
    └── ansi.py         29  ANSI escape code stripping

tests/                      216 passing
deps: claude-agent-sdk, anthropic, aiohttp, python-telegram-bot,
      slack-bolt, slack-sdk, pyyaml
```

## Key Architecture Decisions

1. **SDK is the brain** — no custom agent loop, no tool registry
2. **SDK handles compaction** — listen for compact_boundary, don't second-guess
3. **Memory injected via preset append** — `{type: "preset", preset: "claude_code", append: memory}`
4. **In-process MCP tools** — @tool + create_sdk_mcp_server, factory closure over MemoryStore+SessionDB
5. **isinstance() for SDK messages** — NOT string .type matching (critical pitfall)
6. **Structured output** — SDK output_format + Pydantic model_json_schema() + model_validate()

## SDK Pitfall (learned the hard way)

SDK message classes have NO `.type` attribute. Must use isinstance():
- `SystemMessage` — `.subtype`, `.data` (dict with session_id, model, tools)
- `AssistantMessage` — `.content` (list of TextBlock/ToolUseBlock/ThinkingBlock)
- `ResultMessage` — `.result`, `.total_cost_usd`, `.session_id`, `.subtype`
- `RateLimitEvent` — `.rate_limit_info` (object, NOT `.message`/`.resets_at`)
- `UserMessage` — `.content` (list of ToolResultBlock)

## MCP Tools (in every Aion session)

7 tools registered in-process, no IPC overhead:
- `aion_memory_read/add/replace/remove` — persistent memory CRUD
- `aion_sessions_list` — recent sessions with metadata
- `aion_sessions_search` — FTS5 keyword search across past sessions
- `aion_session_messages` — full conversation replay by ID/prefix

## What Works End-to-End

- CLI one-shot: `uv run python -m aion.cli "do something"` ✓
- CLI REPL: `uv run python -m aion.cli` (interactive with /commands) ✓
- Memory persistence across sessions ✓
- Session tracking and search ✓
- MCP tools (CC uses aion_memory_read etc. naturally) ✓
- Structured output (complete_structured with Pydantic) ✓
- Gateway adapters (written, untested live — need bot tokens)

## Remaining Gaps (priority order)

### 1. Streaming Display
Currently waits for full result. SDK has `include_partial_messages=True`
which yields intermediate AssistantMessages as CC works. Need to wire
this into cli.py for live output and gateway for "typing..." indicators.

### 2. Gateway Session Continuity
Gateway does one query() per message — no conversation memory across messages.
Need to track (platform, chat_id) → CC session_id mapping and use `resume=`
option to continue conversations.

### 3. Delegate/Subagents
This orchestration session spawns parallel CC agents. Aion has no equivalent.
Options:
- SDK `agents` field (AgentDefinition with description/prompt/tools/model)
- SDK `fork_session` for branching
- Direct subprocess CC spawning (like Hermes delegate_task)

### 4. Channel Directory (Phase 3)
Cross-platform routing: resolve "slack:#engineering" → channel ID.
Only matters with 2+ platforms active.

## Orchestration Patterns (for this session type)

This session operates as HIGH-LEVEL ORCHESTRATOR:
- Reads code, analyzes gaps, writes session prompts
- Launches CC agents: `claude --dangerously-skip-permissions -p "$(cat prompt.md)"`
- Monitors via `git log` + `find -newer` (not PTY output)
- Reviews results, commits, pushes
- Agent startup tax: 2-5 min (don't panic)
- Agents may not commit — check `git diff --stat` and commit yourself

Session prompts live in `docs/prompts/`:
- `phase0-structured-output.md` — ✓ done
- `phase2-telegram-gateway.md` — ✓ done (renamed, includes Slack)
- `phase0-mcp-tools.md` — ✓ done

## Reference Repos

| Repo | Path | What to steal |
|------|------|---------------|
| Hermes | ~/dev/hermes-agent | Gateway adapters (13 platforms), process mgmt |
| claude-orchestra | ~/dev/claude-orchestra | SDK patterns, structured output, workplan runner |
| Oro | ~/dev/awo/packages/oro | Orchestration, job queue patterns |

## Commands Cheatsheet

```bash
cd ~/dev/aion
uv run python -m pytest tests/ -q          # run tests (216 passing)
uv run python -m aion.cli "prompt"          # one-shot
uv run python -m aion.cli                   # REPL
uv run python -m aion.cli --gateway telegram # start gateway
uv run python -m aion.cli --sessions        # list sessions
claude auth status                          # verify CC auth

# Launch CC agent on a task:
claude --dangerously-skip-permissions -p "$(cat docs/prompts/PROMPT.md)"
```
