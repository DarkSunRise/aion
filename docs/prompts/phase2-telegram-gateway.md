# Session Prompt: Phase 0.1 — Telegram + Slack Gateway

## Goal

Implement working Telegram AND Slack gateways so Aion can be reached via both.
User sends message → Aion runs SDK query() → response sent back.
This is the minimum viable dogfood: talk to your personal AI agent on Telegram and Slack.

## Boundaries

- Do NOT add structlog, structured output, or any Phase 1 items
- Do NOT implement hooks (Phase 1) — just basic request/response
- Do NOT port media caching, sticker handling, voice transcription, or file uploads from Hermes
- Do NOT add Discord, Matrix, or any adapter besides Telegram, Slack, and CLI
- Do NOT change agent.py, cli.py, memory/, or tests for existing modules
- Keep stdlib logging — do not add structlog
- Tests MUST pass: `uv run python -m pytest tests/ -v`
- Commit after each logical unit (base class, config, adapter, runner)

## Architecture

```
src/aion/gateway/
├── __init__.py          # exports
├── base.py              # ~300 LOC — abstract GatewayAdapter
├── session.py           # ~130 LOC — SessionSource + context prompt builder
├── config.py            # ~200 LOC — GatewayConfig, TelegramConfig, SlackConfig, allowlist
├── runner.py            # ~200 LOC — start adapters, asyncio loop, graceful shutdown
├── adapters/
│   ├── __init__.py
│   ├── telegram.py      # ~500 LOC — python-telegram-bot adapter
│   └── slack.py         # ~400 LOC — slack-bolt adapter (Socket Mode)
src/aion/utils/
├── __init__.py
└── ansi.py              # ~50 LOC — strip ANSI escape codes from CC output
```

## Reference Code

Read these Hermes files for patterns (simplify heavily — Aion needs 10% of this):
- ~/dev/hermes-agent/gateway/platforms/base.py (1452 LOC) → base.py (~300 LOC)
- ~/dev/hermes-agent/gateway/platforms/telegram.py (1906 LOC) → telegram.py (~500 LOC)
- ~/dev/hermes-agent/gateway/platforms/slack.py — Slack adapter patterns
- ~/dev/hermes-agent/gateway/run.py (5889 LOC) → runner.py (~200 LOC)
- ~/dev/hermes-agent/gateway/config.py (829 LOC) → config.py (~200 LOC)

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

### 4. Session context (src/aion/gateway/session.py)
The agent needs to know WHERE it's talking. Port simplified from Hermes
`gateway/session.py` (1061 LOC) → ~130 LOC.

```python
@dataclass
class SessionSource:
    platform: str           # "telegram", "cli", "slack"
    user_id: str
    user_name: Optional[str] = None
    chat_id: str = ""
    chat_type: str = "dm"   # "dm", "group", "channel"
    chat_name: Optional[str] = None

def build_session_context_prompt(source: SessionSource, connected_platforms: list[str]) -> str:
    """Build system prompt section telling agent its context.
    
    Returns something like:
    ## Session Context
    **Source:** Telegram (DM with Kostya)
    **Connected platforms:** telegram
    **Deliver to:** Use `send_message` tool with target format `platform:chat_id`
    """
```

This prompt gets appended to the system_prompt preset alongside memory.
The agent needs this to: address users by name, know its platform, enable
future cross-platform delivery. Read Hermes gateway/session.py for the full
pattern but simplify — skip PII hashing, home channels, thread routing.

### 5. Gateway config (src/aion/gateway/config.py)

```python
@dataclass
class TelegramConfig:
    token: str              # BOT_TOKEN from env or config
    allowed_users: list[str] = field(default_factory=list)  # telegram user IDs

@dataclass
class SlackConfig:
    bot_token: str          # xoxb-... for API calls
    app_token: str          # xapp-... for Socket Mode
    allowed_users: list[str] = field(default_factory=list)
    allowed_channels: list[str] = field(default_factory=list)
    
@dataclass  
class GatewayConfig:
    telegram: Optional[TelegramConfig] = None
    slack: Optional[SlackConfig] = None
```

Load from ~/.aion/config.yaml under `gateway:` key. Support env vars for tokens.

### 6. Telegram adapter (src/aion/gateway/adapters/telegram.py)
Use python-telegram-bot (already a dep). Simplified flow:

```
User sends /start → welcome message
User sends text → 
  1. Check allowed_users (if configured)
  2. Build SessionSource from telegram Update (user_id, username, chat type)
  3. Send "thinking..." typing action
  4. Build session context prompt, append to system_prompt alongside memory
  5. Create AionAgent with user's session
  6. Call agent.run(message_text)
  7. Strip ANSI from response
  8. Split long messages (Telegram 4096 char limit)
  9. Send response
```

Important: python-telegram-bot v20+ is fully async. Use Application class.
DO NOT use the old Updater pattern.

Handle gracefully:
- Messages from unauthorized users (ignore silently or send "not authorized")
- Empty responses from agent
- Agent errors (send error message to user)
- Long responses (split at paragraph boundaries, not mid-word)

### 7. Slack adapter (src/aion/gateway/adapters/slack.py)
Use slack-bolt (add to deps). Use **Socket Mode** (no public URL needed, like Telegram polling).

```
User sends message in Slack →
  1. Check allowed_users / allowed_channels (if configured)
  2. Build SessionSource from Slack event (user_id, channel, thread_ts)
  3. Build session context prompt, append to system_prompt alongside memory
  4. Create AionAgent with user's session
  5. Call agent.run(message_text)
  6. Strip ANSI from response
  7. Split long messages (Slack 4000 char limit per block)
  8. Send response (reply in thread if message was in thread)
```

Key slack-bolt patterns:
```python
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

app = AsyncApp(token=bot_token)

@app.event("message")
async def handle_message(event, say):
    # event["user"], event["channel"], event["text"], event.get("thread_ts")
    ...

handler = AsyncSocketModeHandler(app, app_token)
await handler.start_async()
```

Slack needs TWO tokens:
- `SLACK_BOT_TOKEN` (xoxb-...) — for sending messages
- `SLACK_APP_TOKEN` (xapp-...) — for Socket Mode connection

Handle gracefully:
- Bot mention vs DM vs channel message
- Thread replies (reply in same thread)
- Messages from unauthorized users/channels
- Long responses (split into blocks)
- Bot's own messages (ignore to avoid loops)

### 8. Gateway runner (src/aion/gateway/runner.py)
- Load GatewayConfig from ~/.aion/config.yaml
- Instantiate configured adapters
- Wire on_message callback: message → agent.run() → send response
- Start all adapters as asyncio tasks
- Handle SIGINT/SIGTERM for graceful shutdown

### 9. CLI integration
Add to cli.py (MINIMAL change):
- Add `--gateway` flag to argparse
- When --gateway: load config, start runner, block until shutdown
- This is ~15 lines in cli.py

### 10. pyproject.toml update
- Drop `gemini` optional dependency group
- Add `slack-bolt>=1.20` and `slack-sdk>=3.30` to core deps
- Add `structlog` and `mcp` to core deps (for future phases, not used yet)
- Run `uv sync` after updating to verify deps resolve

### 11. Tests
Add tests/test_gateway.py:
- Test GatewayMessage creation
- Test SessionSource + build_session_context_prompt()
- Test ANSI stripping
- Test message splitting (4096 char for Telegram, 4000 char for Slack)
- Test config loading (both Telegram and Slack configs)
- Mock-based test for telegram adapter message flow
- Mock-based test for slack adapter message flow
- Do NOT test actual Telegram/Slack APIs (no network in tests)

### 12. Config example
Create config.yaml.example in the repo root:
```yaml
gateway:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users:
      - "123456789"  # your telegram user ID
  slack:
    bot_token: ${SLACK_BOT_TOKEN}
    app_token: ${SLACK_APP_TOKEN}
    allowed_channels:
      - "C04ABC123"  # channel ID
```

## Verification

1. `uv run python -m pytest tests/ -v` — all tests pass (old + new)
2. `uv run python -m aion.cli --gateway` — starts without crash (will fail on missing token, that's fine)
3. Code is clean, no unused imports, no debug prints
4. Each commit is atomic and has a descriptive message
