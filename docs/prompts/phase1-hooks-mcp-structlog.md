# Session Prompt: Phase 1 — SDK Hooks, MCP Client, Gateway Continuity, structlog

## Goal

Wire the SDK's lifecycle hooks into agent.py, add external MCP server support,
add gateway session continuity (resume across messages), and migrate to structlog.
After this, Aion is dogfood-ready: rate limit notifications in gateway, completion
callbacks, external tool access, multi-turn gateway conversations, and clean logging.

## Boundaries

- Do NOT rewrite agent.py from scratch — extend the existing run() and continue_session() methods
- Do NOT touch memory/store.py, memory/sessions.py, memory/search.py, schemas.py, or llm.py
- Do NOT change the MCP tools in tools/mcp_tools.py or tools/server.py
- Do NOT add new gateway adapters (no Discord, Matrix, etc.)
- Do NOT change the test infrastructure or conftest — just add new tests
- Tests MUST pass: `uv run python -m pytest tests/ -v`
- Commit after each logical unit (hooks, mcp client, gateway continuity, structlog — 4 commits)
- If you discover the SDK hooks API doesn't work as expected, document what you tried and move on

## Background

### SDK Hooks API

ClaudeAgentOptions has a `hooks` field:
```python
hooks: dict[
    Literal['PreToolUse', 'PostToolUse', 'PostToolUseFailure',
            'UserPromptSubmit', 'Stop', 'SubagentStop',
            'PreCompact', 'Notification', 'SubagentStart',
            'PermissionRequest'],
    list[HookMatcher]
] | None
```

HookMatcher is a dataclass:
```python
@dataclass
class HookMatcher:
    matcher: str | None = None  # glob pattern to match tool names, or None for all
    hooks: list[HookCallback]   # list of async callbacks
    timeout: float | None = None
```

Each hook callback receives `(input, tool_name_or_none, context)` and returns a dict.
Hook input types (all TypedDict-like, accessed as dicts):
- StopHookInput — agent is about to stop
- NotificationHookInput — agent sends a notification/status update
- PreCompactHookInput — context about to be compacted
- RateLimitEvent — already handled in stream, but hooks give pre-emptive control
- PreToolUseHookInput — before a tool runs
- PostToolUseHookInput — after a tool runs
- SubagentStartHookInput / SubagentStopHookInput — subagent lifecycle

### MCP Client

ClaudeAgentOptions.mcp_servers accepts external servers:
```python
mcp_servers: dict[str, McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig | McpSdkServerConfig]
```

For stdio servers (most common):
```python
from claude_agent_sdk import McpStdioServerConfig  # or construct manually
# Config format: {"command": "uvx", "args": ["some-mcp-server"], "env": {...}}
```

Aion config.yaml should support:
```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
  github:
    command: "uvx"
    args: ["mcp-server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

### Gateway Session Continuity

Currently each Telegram/Slack message creates a brand new session.
For dogfooding, messages from the same user within a time window should
continue the same CC session (using `resume=cc_session_id`).

Pattern:
1. After each message, store the CC session ID and timestamp
2. On next message from same user, check if within continuity window (default: 30 min)
3. If within window: use continue_session() with the stored CC session ID
4. If outside window: start fresh session

This state lives in SessionDB or a simple in-memory dict per gateway runner.

## Step-by-Step

### 1. Read existing code first
- Read src/aion/agent.py (388 LOC)
- Read src/aion/gateway/runner.py (178 LOC)
- Read src/aion/gateway/session.py (77 LOC)
- Read src/aion/config.py (143 LOC)
- Read tests/test_agent.py and tests/test_gateway.py

### 2. SDK Hooks (Commit 1: "feat: SDK lifecycle hooks")

Add a hooks module: `src/aion/hooks.py` (~120 LOC)

Create hook callbacks as async functions:

```python
"""SDK lifecycle hooks for Aion agent."""

import logging
from typing import Any, Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

# Type for gateway notification callback
NotifyCallback = Callable[[str, str], Awaitable[None]]  # (session_id, message) -> None


class AionHooks:
    """Manages SDK hooks with optional gateway notification forwarding."""

    def __init__(self, notify_callback: Optional[NotifyCallback] = None):
        self._notify = notify_callback
        self._rate_limit_count = 0

    def build_hooks_dict(self) -> dict:
        """Build the hooks dict for ClaudeAgentOptions."""
        from claude_agent_sdk import HookMatcher
        return {
            "Stop": [HookMatcher(hooks=[self._on_stop])],
            "Notification": [HookMatcher(hooks=[self._on_notification])],
            "PreCompact": [HookMatcher(hooks=[self._on_pre_compact])],
            "PreToolUse": [HookMatcher(hooks=[self._on_pre_tool_use])],
            "PostToolUse": [HookMatcher(hooks=[self._on_post_tool_use])],
            "SubagentStart": [HookMatcher(hooks=[self._on_subagent_start])],
            "SubagentStop": [HookMatcher(hooks=[self._on_subagent_stop])],
        }

    async def _on_stop(self, input, tool_name, context):
        """Agent is stopping — log reason."""
        logger.info("Agent stopping: %s", input)
        return {}

    async def _on_notification(self, input, tool_name, context):
        """Agent sent a status notification — forward to gateway if connected."""
        message = input.get("message", "") if isinstance(input, dict) else str(input)
        logger.info("Agent notification: %s", message)
        if self._notify:
            session_id = context.session_id if hasattr(context, 'session_id') else ""
            await self._notify(session_id, message)
        return {}

    async def _on_pre_compact(self, input, tool_name, context):
        """Context about to be compacted — log for monitoring."""
        logger.info("Context compaction starting")
        return {}

    async def _on_pre_tool_use(self, input, tool_name, context):
        """Before tool execution — log tool name for debugging."""
        logger.debug("Tool starting: %s", tool_name)
        return {}

    async def _on_post_tool_use(self, input, tool_name, context):
        """After tool execution — log for debugging."""
        logger.debug("Tool completed: %s", tool_name)
        return {}

    async def _on_subagent_start(self, input, tool_name, context):
        """Subagent spawned."""
        logger.info("Subagent starting")
        return {}

    async def _on_subagent_stop(self, input, tool_name, context):
        """Subagent finished."""
        logger.info("Subagent stopped")
        return {}
```

Wire into agent.py:
- In AionAgent.__init__, create self._hooks = AionHooks()
- Accept optional `notify_callback` param on AionAgent.__init__
- In run() and continue_session(), add `hooks=self._hooks.build_hooks_dict()` to options
- IMPORTANT: if the SDK raises on any hook signature mismatch, catch it, log a warning, and fall back to no hooks. Don't let hooks break the agent.

Tests (add to tests/test_agent.py or new tests/test_hooks.py):
- Test AionHooks.build_hooks_dict() returns correct structure
- Test each callback can be called with mock input without error
- Test notify_callback is called when _on_notification fires
- Test hooks are passed through to ClaudeAgentOptions in agent.run()

### 3. MCP Client — External Servers (Commit 2: "feat: external MCP server support")

Update config.py:
- Add `mcp_servers` section to AionConfig
- Parse config.yaml mcp_servers entries into a dict of server configs
- Support env var interpolation in server configs (reuse existing interpolate_env)

```python
# In config.py, add to AionConfig:
mcp_servers: dict = field(default_factory=dict)  # name -> {command, args, env}
```

Update agent.py:
- In run() where mcp_servers are built, also load external servers from config
- Convert config entries to the format the SDK expects
- The SDK accepts plain dicts for stdio servers: {"command": "...", "args": [...], "env": {...}}

```python
# In agent.py run(), extend the mcp dict:
mcp = {"aion": self._aion_mcp}
# Add external MCP servers from config
for name, server_cfg in self.config.mcp_servers.items():
    mcp[name] = server_cfg  # SDK accepts dict format directly
if mcp_servers:
    mcp.update(mcp_servers)
options.mcp_servers = mcp
```

Do the same in continue_session().

Tests:
- Test config parsing with mcp_servers section
- Test env var interpolation in mcp server configs
- Test external servers are merged into options.mcp_servers alongside aion server
- Mock-based — do NOT try to actually start MCP servers in tests

### 4. Gateway Session Continuity (Commit 3: "feat: gateway session continuity")

Add session tracking to the gateway runner so consecutive messages from the
same user continue the same CC conversation.

Add to gateway/session.py:
```python
import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ActiveSession:
    cc_session_id: str
    aion_session_id: str
    last_activity: float
    platform: str
    user_id: str

class SessionTracker:
    """Track active sessions for gateway continuity."""

    def __init__(self, continuity_window: int = 1800):  # 30 min default
        self._sessions: dict[str, ActiveSession] = {}  # key: "platform:user_id"
        self._continuity_window = continuity_window

    def _key(self, platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}"

    def get_active(self, platform: str, user_id: str) -> Optional[ActiveSession]:
        """Get active session if within continuity window."""
        key = self._key(platform, user_id)
        session = self._sessions.get(key)
        if session and (time.time() - session.last_activity) < self._continuity_window:
            return session
        # Expired or not found
        if key in self._sessions:
            del self._sessions[key]
        return None

    def update(self, platform: str, user_id: str,
               cc_session_id: str, aion_session_id: str) -> None:
        """Update or create active session."""
        key = self._key(platform, user_id)
        self._sessions[key] = ActiveSession(
            cc_session_id=cc_session_id,
            aion_session_id=aion_session_id,
            last_activity=time.time(),
            platform=platform,
            user_id=user_id,
        )

    def clear(self, platform: str, user_id: str) -> None:
        """Clear active session (e.g., on /new command)."""
        key = self._key(platform, user_id)
        self._sessions.pop(key, None)
```

Update runner.py _handle_message():
- Create SessionTracker on GatewayRunner.__init__
- In _handle_message: check for active session → use continue_session() if found
- After agent response: extract CC session ID from result, update tracker
- Add `/new` command handling in adapters to clear the session

Update Telegram adapter:
- Add `/new` command handler that clears the session via callback
- Pass session_tracker or a "clear session" callback through

Tests:
- Test SessionTracker.get_active within window returns session
- Test SessionTracker.get_active outside window returns None
- Test SessionTracker.update creates new session
- Test SessionTracker.clear removes session
- Test _handle_message uses continue_session when active session exists
- Test _handle_message starts fresh when no active session

### 5. structlog Migration (Commit 4: "feat: migrate to structlog")

Replace stdlib logging with structlog across all source files.

Install: add `structlog>=24.0` to pyproject.toml dependencies. Run `uv sync`.

Create src/aion/log.py:
```python
"""Structured logging configuration."""

import logging
import structlog

def configure_logging(json_output: bool = False, level: str = "INFO"):
    """Configure structlog.

    Args:
        json_output: True for JSON (gateway/production), False for colored dev output
        level: Log level string
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper()))
```

Then in EVERY source file that uses logging, replace:
```python
# OLD:
import logging
logger = logging.getLogger(__name__)

# NEW:
import structlog
logger = structlog.get_logger(__name__)
```

Files to update (search for `import logging` and `getLogger`):
- src/aion/agent.py
- src/aion/cli.py
- src/aion/config.py
- src/aion/llm.py
- src/aion/hooks.py (new file from step 2)
- src/aion/memory/store.py — NO, boundary says don't touch
- src/aion/memory/sessions.py — NO, boundary says don't touch
- src/aion/gateway/runner.py
- src/aion/gateway/base.py
- src/aion/gateway/adapters/telegram.py
- src/aion/gateway/adapters/slack.py

WAIT — boundaries say don't touch memory/store.py and memory/sessions.py.
Those still use stdlib logging. That's fine — structlog wraps stdlib, so
stdlib loggers still get formatted by structlog's ProcessorFormatter.
The stdlib loggers in memory/ will automatically use structlog formatting
once configure_logging() is called. No changes needed to those files.

Call configure_logging() early in:
- cli.py main() — json_output=False for CLI, True when --gateway
- gateway/runner.py start_gateway() — json_output=True

Tests:
- Test configure_logging() doesn't crash in both modes
- Test that structlog loggers can log at all levels without error
- Verify existing tests still pass (structlog is backwards compatible with stdlib)

## Verification

After all 4 commits:
1. `uv run python -m pytest tests/ -v` — ALL tests pass (old + new)
2. `uv run python -c "from aion.hooks import AionHooks; print(AionHooks().build_hooks_dict().keys())"` works
3. `uv run python -c "from aion.log import configure_logging; configure_logging()"` works
4. No unused imports, no debug prints
5. `uv sync` resolves cleanly
6. Each commit builds on the previous — if hooks fail, the rest still works
