"""SDK lifecycle hooks for Aion agent.

Wires into claude-agent-sdk's hook system to log lifecycle events,
forward notifications to gateway, and track rate limits.
"""

from typing import Any, Optional, Callable, Awaitable

import structlog
from claude_agent_sdk import HookMatcher

logger = structlog.get_logger(__name__)

# Type for gateway notification callback
NotifyCallback = Callable[[str, str], Awaitable[None]]  # (session_id, message) -> None


class AionHooks:
    """Manages SDK hooks with optional gateway notification forwarding."""

    def __init__(self, notify_callback: Optional[NotifyCallback] = None):
        self._notify = notify_callback
        self._rate_limit_count = 0

    def build_hooks_dict(self) -> dict:
        """Build the hooks dict for ClaudeAgentOptions."""
        return {
            "Stop": [HookMatcher(hooks=[self._on_stop])],
            "Notification": [HookMatcher(hooks=[self._on_notification])],
            "PreCompact": [HookMatcher(hooks=[self._on_pre_compact])],
            "PreToolUse": [HookMatcher(hooks=[self._on_pre_tool_use])],
            "PostToolUse": [HookMatcher(hooks=[self._on_post_tool_use])],
            "SubagentStart": [HookMatcher(hooks=[self._on_subagent_start])],
            "SubagentStop": [HookMatcher(hooks=[self._on_subagent_stop])],
        }

    async def _on_stop(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """Agent is stopping — log reason."""
        session_id = input.get("session_id", "") if isinstance(input, dict) else ""
        logger.info("Agent stopping (session=%s)", session_id)
        return {}

    async def _on_notification(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """Agent sent a status notification — forward to gateway if connected."""
        message = input.get("message", "") if isinstance(input, dict) else str(input)
        title = input.get("title", "") if isinstance(input, dict) else ""
        logger.info("Agent notification: %s%s", f"[{title}] " if title else "", message)
        if self._notify:
            session_id = input.get("session_id", "") if isinstance(input, dict) else ""
            await self._notify(session_id, message)
        return {}

    async def _on_pre_compact(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """Context about to be compacted — log for monitoring."""
        trigger = input.get("trigger", "unknown") if isinstance(input, dict) else "unknown"
        logger.info("Context compaction starting (trigger=%s)", trigger)
        return {}

    async def _on_pre_tool_use(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """Before tool execution — log tool name for debugging."""
        name = input.get("tool_name", tool_name or "?") if isinstance(input, dict) else (tool_name or "?")
        logger.debug("Tool starting: %s", name)
        return {}

    async def _on_post_tool_use(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """After tool execution — log for debugging."""
        logger.debug("Tool completed: %s", tool_name or "?")
        return {}

    async def _on_subagent_start(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """Subagent spawned."""
        logger.info("Subagent starting")
        return {}

    async def _on_subagent_stop(self, input: Any, tool_name: Optional[str], context: Any) -> dict:
        """Subagent finished."""
        logger.info("Subagent stopped")
        return {}
