# Session Prompt: Phase 2 — Telegram Gateway

## Goal

Implement a working Telegram gateway so Aion can be reached via Telegram bot.
User sends message on Telegram → Aion runs SDK query() → response sent back.
This is the minimum viable dogfood: talk to your personal AI agent on Telegram.

## Boundaries

- Do NOT add structlog, structured output, or any Phase 1 items
- Do NOT implement hooks (Phase 3) — just basic request/response
- Do NOT port media caching, sticker handling, voice transcription, or file uploads from Hermes
- Do NOT add Discord, Slack, or any adapter besides Telegram + CLI
- Do NOT change agent.py, cli.py, memory/, or tests for existing modules
- Keep stdlib logging — do not add structlog
- Tests MUST pass: `uv run python -m pytest tests/ -v`
- Commit after each logical unit (base class, config, adapter, runner)

## Architecture

```
src/aion/gateway/
├── __init__.py          # exports
├── base.py              # ~300 LOC — abstract GatewayAdapter
├── config.py            # ~150 LOC — GatewayConfig, TelegramConfig, allowlist
├── runner.py            # ~200 LOC — start adapters, asyncio loop, graceful shutdown
├── adapters/
│   ├── __init__.py
│   └── telegram.py      # ~500 LOC — python-telegram-bot adapter
src/aion/utils/
├── __init__.py
└── ansi.py              # ~50 LOC — strip ANSI escape codes from CC output
```

## Reference Code

Read these Hermes files for patterns (simplify heavily — Aion needs 10% of this):
- ~/dev/hermes-agent/gateway/platforms/base.py (1452 LOC) → base.py (~300 LOC)
- ~/dev/hermes-agent/gateway/platforms/telegram.py (1906 LOC) → telegram.py (~500 LOC)
- ~/dev/hermes-agent/gateway/run.py (5889 LOC) → runner.py (~200 LOC)
- ~/dev/hermes-agent/gateway/config.py (829 LOC) → config.py (~150 LOC)

## Step-by-Step

### 1. Read existing code first
- Read src/aion/agent.py — understand how query() is called
- Read src/aion/config.py — understand config pattern
- Read src/aion/cli.py — understand CLI entry point
- Skim Hermes gateway files listed above for patterns

### 2. ANSI stripping utility (src/aion/utils/ansi.py)
- Single function: `strip_ansi(text: str) -> str`
- Compile regex once at module level
- Handle all common escape sequences (colors, cursor, etc.)

### 3. Gateway base class (src/aion/gateway/base.py)
Simplified from Hermes. Core interface:

```python
@dataclass
class GatewayMessage:
    text: str
    sender_id: str
    chat_id: str
    platform: str
    reply_to: Optional[str] = None
    metadata: dict = field(default_factory=dict)

class GatewayAdapter(ABC):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(self, chat_id: str, text: str, **kwargs) -> None: ...
    # on_message callback set by runner
```

Skip from Hermes: fatal error tracking, connection state machine, typing indicators,
edit_message, media sending, image/audio/document caching. We can add those later.

### 4. Gateway config (src/aion/gateway/config.py)

```python
@dataclass
class TelegramConfig:
    token: str              # BOT_TOKEN from env or config
    allowed_users: list[str] = field(default_factory=list)  # telegram user IDs
    
@dataclass  
class GatewayConfig:
    telegram: Optional[TelegramConfig] = None
```

Load from ~/.aion/config.yaml under `gateway:` key. Support env vars for token.

### 5. Telegram adapter (src/aion/gateway/adapters/telegram.py)
Use python-telegram-bot (already a dep). Simplified flow:

```
User sends /start → welcome message
User sends text → 
  1. Check allowed_users (if configured)
  2. Send "thinking..." typing action
  3. Create AionAgent with user's session
  4. Call agent.run(message_text)
  5. Strip ANSI from response
  6. Split long messages (Telegram 4096 char limit)
  7. Send response
```

Important: python-telegram-bot v20+ is fully async. Use Application class.
DO NOT use the old Updater pattern.

Handle gracefully:
- Messages from unauthorized users (ignore silently or send "not authorized")
- Empty responses from agent
- Agent errors (send error message to user)
- Long responses (split at paragraph boundaries, not mid-word)

### 6. Gateway runner (src/aion/gateway/runner.py)
- Load GatewayConfig from ~/.aion/config.yaml
- Instantiate configured adapters
- Wire on_message callback: message → agent.run() → send response
- Start all adapters as asyncio tasks
- Handle SIGINT/SIGTERM for graceful shutdown

### 7. CLI integration
Add to cli.py (MINIMAL change):
- Add `--gateway` flag to argparse
- When --gateway: load config, start runner, block until shutdown
- This is ~15 lines in cli.py

### 8. pyproject.toml update
- Drop `gemini` optional dependency group
- Add `structlog` and `mcp` to core deps (for future phases, not used yet)
- Add optional extras: `slack = ["slack-bolt>=1.20"]`

### 9. Tests
Add tests/test_gateway.py:
- Test GatewayMessage creation
- Test ANSI stripping
- Test message splitting (4096 char limit)
- Test config loading
- Mock-based test for telegram adapter message flow
- Do NOT test actual Telegram API (no network in tests)

### 10. Config example
Create ~/.aion/config.yaml.example:
```yaml
gateway:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users:
      - "123456789"  # your telegram user ID
```

## Verification

1. `uv run python -m pytest tests/ -v` — all tests pass (old + new)
2. `uv run python -m aion.cli --gateway` — starts without crash (will fail on missing token, that's fine)
3. Code is clean, no unused imports, no debug prints
4. Each commit is atomic and has a descriptive message
