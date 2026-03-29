# Hermes → Aion Migration Workplan

> Generated: 2026-03-29
> Source: ~/dev/hermes-agent (67K LOC, v0.4.0)
> Target: ~/dev/aion (945 LOC, v0.1.0)

## Architecture Decision

Aion wraps `claude-agent-sdk` — Claude Code handles tools, terminal, files, browser natively.
What Aion needs from Hermes is the **gateway layer** (messaging platform adapters) and supporting infrastructure.

We do NOT port: tool registry, file_operations, fuzzy_match, patch_parser, approval system, execution environments, browser tools, web tools — Claude Code provides all of these.

## Phase 1: Gateway Foundation (~3.5K LOC)

Port and adapt these Hermes files:

| Source | Target | LOC | Notes |
|--------|--------|-----|-------|
| `gateway/platforms/base.py` | `src/aion/gateway/base.py` | 1452 | Strip Hermes-specific imports, use AionConfig |
| `gateway/config.py` | `src/aion/gateway/config.py` | 829 | Simplify — Aion has fewer platform options initially |
| `gateway/session.py` | `src/aion/gateway/session.py` | 1061 | Session routing, topic management |
| `gateway/delivery.py` | `src/aion/gateway/delivery.py` | 346 | Message chunking, retry |
| `gateway/stream_consumer.py` | `src/aion/gateway/stream.py` | 202 | Bridge sync agent → async platform |

Adaptations needed:
- Replace `hermes_constants` refs with `aion.config`
- Replace `hermes_cli.config` with `aion.config.load_config()`
- Base adapter's `process_message()` calls `AionAgent.run()` instead of Hermes agent loop
- Session keys use Aion's SessionDB

## Phase 2: Telegram Adapter (~2.1K LOC)

| Source | Target | LOC | Notes |
|--------|--------|-----|-------|
| `gateway/platforms/telegram.py` | `src/aion/gateway/adapters/telegram.py` | 1906 | Core adapter |
| `gateway/platforms/telegram_network.py` | `src/aion/gateway/adapters/telegram_network.py` | 233 | Reconnect layer |

Adaptations:
- Telegram adapter is the most battle-tested (primary platform for Hermes)
- Uses python-telegram-bot (already in Aion's deps)
- Needs allowlist support (who can message the bot)
- Voice/sticker/document handlers can be simplified initially

## Phase 3: Gateway Runner (~800 LOC, new code)

Create `src/aion/gateway/runner.py`:
- Parse config to determine which adapters to start
- Start adapters as asyncio tasks
- Route messages: adapter → AionAgent.run() → adapter.send_response()
- Handle graceful shutdown (SIGINT/SIGTERM)
- Wire into CLI: `aion --gateway`

## Phase 4: Supporting Utils (~1.5K LOC)

| Source | Target | LOC | Notes |
|--------|--------|-----|-------|
| `tools/ansi_strip.py` | `src/aion/utils/ansi.py` | 44 | Strip ANSI from CC output before sending to platform |
| `tools/url_safety.py` | `src/aion/utils/url_safety.py` | 96 | SSRF prevention for webhooks |
| `utils.py` | `src/aion/utils/atomic.py` | 107 | Atomic file writes |
| `agent/redact.py` (diff) | merge into `src/aion/redact.py` | ~120 | Hermes has more patterns (165 LOC vs Aion's 43) |
| `hermes_time.py` | `src/aion/utils/time.py` | 120 | Timezone-aware timestamps |

## Phase 5: Discord Adapter (~2.2K LOC)

| Source | Target | LOC | Notes |
|--------|--------|-----|-------|
| `gateway/platforms/discord.py` | `src/aion/gateway/adapters/discord.py` | 2212 | Discord.py based |

Lower priority — Telegram is the primary platform.

## NOT Porting (Claude Code provides these)

- Tool registry, toolsets, toolset_distributions
- File operations, fuzzy match, patch parser
- Terminal tool, execution environments
- Browser tool, web tools
- Code execution tool
- Vision tools (CC has native vision)
- Delegate tool (CC has native delegation)
- Todo tool, clarify tool
- Image generation tool
- MCP client (CC has native MCP)

## NOT Porting (not needed for personal agent)

- Honcho integration (external memory service)
- ACP adapter (agent communication protocol)
- Skills hub marketplace (skills come from CC)
- Cron system (use system cron or CC's built-in)
- Process registry (CC manages its own processes)
- Checkpoint manager (git handles this)

## Success Criteria

- `aion --gateway` starts Telegram bot
- User sends message on Telegram → Aion routes to CC → response sent back
- Memory persists across Telegram conversations
- Session search works from Telegram
- Voice messages transcribed and processed
- ANSI stripped from CC output before sending to Telegram
