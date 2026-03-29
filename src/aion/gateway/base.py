"""
Abstract gateway adapter interface.

All platform adapters (Telegram, Slack) inherit from this and implement
the required methods. Simplified from Hermes BasePlatformAdapter.
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


@dataclass
class GatewayMessage:
    """A message received from a messaging platform."""

    text: str
    sender_id: str
    chat_id: str
    platform: str
    sender_name: Optional[str] = None
    reply_to: Optional[str] = None
    metadata: dict = field(default_factory=dict)


# Type for the callback the runner sets on each adapter
MessageCallback = Callable[[GatewayMessage], Awaitable[str]]


def split_message(text: str, max_length: int) -> list[str]:
    """Split a long message into chunks that fit within *max_length*.

    Tries to split at paragraph boundaries (double newline), then at
    single newlines, then at spaces. Never splits mid-word unless a
    single word exceeds *max_length*.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to find a good split point
        chunk = remaining[:max_length]

        # Prefer paragraph boundary
        split_at = chunk.rfind("\n\n")
        if split_at > max_length // 4:
            chunks.append(remaining[: split_at].rstrip())
            remaining = remaining[split_at:].lstrip("\n")
            continue

        # Then single newline
        split_at = chunk.rfind("\n")
        if split_at > max_length // 4:
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at + 1 :]
            continue

        # Then space
        split_at = chunk.rfind(" ")
        if split_at > max_length // 4:
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at + 1 :]
            continue

        # Hard split — no good boundary found
        chunks.append(remaining[:max_length])
        remaining = remaining[max_length:]

    return [c for c in chunks if c]


class GatewayAdapter(ABC):
    """Abstract base for messaging platform adapters."""

    platform_name: str = "unknown"
    max_message_length: int = 4096

    def __init__(self):
        self.on_message: Optional[MessageCallback] = None
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Connect to the platform and start receiving messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect and clean up."""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, **kwargs) -> None:
        """Send a message to the specified chat."""
        ...

    async def send_long_message(self, chat_id: str, text: str, **kwargs) -> None:
        """Send a message, splitting it if it exceeds the platform limit."""
        chunks = split_message(text, self.max_message_length)
        for chunk in chunks:
            await self.send_message(chat_id, chunk, **kwargs)

    @property
    def is_running(self) -> bool:
        return self._running
