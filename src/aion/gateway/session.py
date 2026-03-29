"""
Session context for gateway messages.

Tells the agent WHERE it's talking — platform, user, chat type.
Simplified from Hermes gateway/session.py (~1061 LOC → ~100 LOC).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SessionSource:
    """Describes where a message originated from."""

    platform: str  # "telegram", "slack", "cli"
    user_id: str
    user_name: Optional[str] = None
    chat_id: str = ""
    chat_type: str = "dm"  # "dm", "group", "channel"
    chat_name: Optional[str] = None
    thread_id: Optional[str] = None

    @property
    def description(self) -> str:
        """Human-readable description of the source."""
        if self.platform == "cli":
            return "CLI terminal"

        if self.chat_type == "dm":
            who = self.user_name or self.user_id or "user"
            return f"DM with {who}"
        elif self.chat_type == "group":
            return f"group: {self.chat_name or self.chat_id}"
        elif self.chat_type == "channel":
            return f"channel: {self.chat_name or self.chat_id}"
        return self.chat_name or self.chat_id


def build_session_context_prompt(
    source: SessionSource,
    connected_platforms: list[str],
) -> str:
    """Build system prompt section telling the agent its context.

    This gets appended to the system_prompt preset alongside memory,
    so the agent knows where it's talking and who to.
    """
    lines = [
        "## Current Session Context",
        "",
        f"**Source:** {source.platform.title()} ({source.description})",
    ]

    if source.user_name:
        lines.append(f"**User:** {source.user_name}")

    # Platform-specific notes
    if source.platform == "slack":
        lines.append("")
        lines.append(
            "**Platform notes:** You are running inside Slack. "
            "You do NOT have access to Slack-specific APIs — you cannot search "
            "channel history, pin messages, manage channels, or list users. "
            "If the user asks, explain that you can only read messages sent "
            "directly to you and respond."
        )

    # Connected platforms
    platform_strs = ["local (files on this machine)"]
    for p in connected_platforms:
        if p != "cli":
            platform_strs.append(f"{p}: Connected")

    lines.append(f"**Connected platforms:** {', '.join(platform_strs)}")

    return "\n".join(lines)
