# Handover: Aion v0.3.0 Dogfood — 2026-03-29

## Context

Aion is a Python extension of Hermes (NOT a replacement). It provides a modernized
brain (claude-agent-sdk, subscription-native, structured output) for Hermes's body
(gateway, skills, cron, tools, memory). Both are Python. The user likes Hermes's
memory system — don't position Aion's as better.

All planned implementation phases are complete. The project is in dogfood phase.

## Current State

- Version: 0.3.0 | ~3,900 LOC | 258 tests | all passing
- `aion` command at ~/.local/bin/aion (symlink to .venv/bin/aion)
- Config: ~/.aion/config.yaml
- Repo: ~/dev/aion (DarkSunRise/aion), main branch, fully pushed

## Critical Knowledge (must know)

1. **SDK structured output pitfall**: output_format with json_schema returns data via
   a synthetic `StructuredOutput` ToolUseBlock (block.input), NOT via
   ResultMessage.structured_output. Fixed in llm.py but verify search.py works.

2. **Hermes is Python** (not TS). claude-orchestra and oro are TS.
   Language split: Python runtime (Hermes/Aion) vs TS orchestration (Oro).

3. **Auto-title generation** runs in agent.py finally block. Tests must mock
   `agent._generate_title = AsyncMock(return_value=None)` or they hang.

4. **Permission mode** defaults to bypassPermissions — fine for personal use.

## What Works

- One-shot: `aion "your prompt"`
- REPL: `aion` (with /help, /sessions, /search, /resume, /memory, /quit)
- Session listing: `aion --sessions`
- Session search: `aion --search "query"`
- Session resume: `aion --resume PREFIX` or `aion --continue`
- Gateway: `aion --gateway telegram` (needs bot token in config)
- Auto titles on sessions
- Structured output (Pydantic + SDK)
- SDK hooks (7 lifecycle events)
- External MCP servers via config.yaml
- Gateway session continuity (30min window)
- structlog (JSON in gateway, colored in CLI)

## Next Steps (priority order)

1. **Dogfood the CLI** — use `aion` for real work, file bugs
2. **Verify search.py** — LLM session search was silently broken before the
   structured output fix. Test: `aion --search "math"` should return summaries.
3. **Telegram gateway** — add bot token to ~/.aion/config.yaml, run it
4. **Remaining code items**: streaming, delegate_task, PermissionRequest hook

## Files to Read First

- docs/HANDOVER.md — full project context and architecture
- docs/SESSION-LEARNINGS.md — pitfalls and decisions from this session
- src/aion/agent.py — core agent (the file you'll modify most)
- src/aion/llm.py — aux LLM calls (structured output lives here)
