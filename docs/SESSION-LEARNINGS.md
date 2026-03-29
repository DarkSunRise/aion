# Session Learnings Log

## Session 2026-03-29 — Hermes Relationship Correction + Phase 1 + Dogfood Prep

### Discoveries

1. **Hermes is Python, not TypeScript.** We had 18 misleading statements across 9 docs
   positioning Aion as a replacement/migration from Hermes, and implying Hermes was TS.
   Hermes IS Python (~67K LOC). Aion extends it — same language, direct code sharing.

2. **Aion's memory is NOT better than Hermes's.** Hermes memory has: fcntl locking,
   atomic writes via tempfile+os.replace, frozen snapshot pattern (prefix cache stability),
   injection scanning, thread safety, FTS5 sanitization, write contention retry.
   Aion's memory is a subset. User explicitly prefers Hermes's memory.

3. **Language split is clean**: Python runtime (Hermes/Aion) vs TS orchestration
   (Oro/claude-orchestra/AWO). Aion in Python is correct.

4. **All Phase 0 and Phase 1 items were already done or got done this session.**
   The roadmap was stale — structured output, gateway, MCP tools were already shipped.

### SDK Pitfalls Found

1. **Structured output uses synthetic ToolUseBlock, not ResultMessage.structured_output.**
   When `output_format={"type": "json_schema", "schema": ...}` is set, the SDK returns
   the validated data in an AssistantMessage containing a ToolUseBlock with
   `name="StructuredOutput"` and the data in `block.input`. `ResultMessage.structured_output`
   is always None. This was silently breaking `complete_structured()` and therefore all
   typed LLM calls (search summaries, session titles).

2. **Auto-title generation needs to be async but runs in finally block.**
   `_generate_title()` does an aux LLM call. Tests that mock `query()` but not
   `_generate_title()` will hang because the aux call tries to actually query the SDK.
   Always mock `_generate_title = AsyncMock(return_value=None)` in agent test fixtures.

### Decisions Made

1. **Aion extends Hermes, not replaces.** Aion's agent.py (claude-agent-sdk) replaces
   Hermes's run_agent.py (OpenAI-compatible). Everything else stays: gateway, skills,
   cron, tools, memory, process management.

2. **hermes-fork in AWO is Python-to-Python**, not cross-language. The integration path
   is direct code swap, not IPC or MCP bridge.

3. **Dogfood locally first** via CLI before Telegram. The REPL + one-shot mode is
   fully functional now.

### What Changed (9 commits)

```
8d4fedb chore: add config.yaml.example for dogfooding
7541d48 feat: auto-title generation + fix structured output extraction
9354903 docs: update HANDOVER.md — v0.3.0, all phases complete, dogfood remaining
5edfc66 feat: migrate to structlog
4c2f2a5 feat: gateway session continuity
f26919f feat: external MCP server support
ce3e46d feat: SDK lifecycle hooks
aaf52a2 docs: Phase 1 session prompt — hooks, MCP client, gateway continuity, structlog
5e85b85 docs: correct Hermes relationship — Aion extends, not replaces
```

### Current State

- **Version**: 0.3.0 | 3,814+ LOC | 258 tests | all passing
- **`aion` command**: available at ~/.local/bin/aion (symlink to .venv)
- **Config**: ~/.aion/config.yaml (created, sensible defaults)
- **Titles**: auto-generated via complete_structured() + SessionTitle schema
- **All phases done**: structured output, gateway (Telegram+Slack), MCP (tools+client),
  SDK hooks, structlog, session continuity

### What's Next (priority order)

1. **Dogfood the CLI** — use `aion` for real tasks, discover bugs
2. **Fix search.py** — verify LLM-powered session search works now that
   complete_structured() is fixed (it was silently failing before)
3. **Telegram gateway** — set up bot token, test `aion --gateway telegram`
4. **Streaming display** — typing indicators in gateway
5. **delegate_task** — subagent spawning
6. **PermissionRequest hook** — handle permission prompts in gateway
