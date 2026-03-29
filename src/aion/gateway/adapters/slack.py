"""
Slack gateway adapter.

Uses slack-bolt with Socket Mode (no public URL needed).
Simplified from Hermes SlackAdapter.
"""

import asyncio
import re
from typing import Optional

import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ..base import GatewayAdapter, GatewayMessage
from ..config import SlackConfig
from ..session import SessionSource

logger = structlog.get_logger(__name__)


class SlackAdapter(GatewayAdapter):
    """Slack bot adapter using Socket Mode."""

    platform_name = "slack"
    max_message_length = 4000

    def __init__(self, config: SlackConfig):
        super().__init__()
        self.config = config
        self._app: Optional[AsyncApp] = None
        self._handler: Optional[AsyncSocketModeHandler] = None
        self._bot_user_id: Optional[str] = None
        self._user_name_cache: dict[str, str] = {}

    def _is_allowed(self, user_id: str, channel_id: str) -> bool:
        """Check allowlist (empty lists = allow all)."""
        if self.config.allowed_users and user_id not in self.config.allowed_users:
            return False
        if self.config.allowed_channels and channel_id not in self.config.allowed_channels:
            return False
        return True

    async def _resolve_user_name(self, user_id: str) -> Optional[str]:
        """Resolve a Slack user ID to a display name, with caching."""
        if not user_id or not self._app:
            return None
        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]

        try:
            result = await self._app.client.users_info(user=user_id)
            user = result.get("user", {})
            profile = user.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_id
            )
            self._user_name_cache[user_id] = name
            return name
        except Exception as e:
            logger.debug("Slack: users.info failed for %s: %s", user_id, e)
            self._user_name_cache[user_id] = user_id
            return user_id

    def _build_source(
        self, user_id: str, user_name: Optional[str],
        channel_id: str, channel_type: str, thread_ts: Optional[str],
    ) -> SessionSource:
        """Build a SessionSource from Slack event data."""
        is_dm = channel_type == "im"
        chat_type = "dm" if is_dm else "channel"

        return SessionSource(
            platform="slack",
            user_id=user_id,
            user_name=user_name,
            chat_id=channel_id,
            chat_type=chat_type,
            thread_id=thread_ts,
        )

    async def _handle_message_event(self, event: dict) -> None:
        """Handle an incoming Slack message event."""
        # Ignore bot messages (including our own)
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        # Ignore edits and deletions
        subtype = event.get("subtype")
        if subtype in ("message_changed", "message_deleted"):
            return

        text = event.get("text", "")
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        ts = event.get("ts", "")
        channel_type = event.get("channel_type", "")
        is_dm = channel_type == "im"

        # Thread handling: in channels, use ts as fallback so each
        # top-level mention starts a new thread
        if is_dm:
            thread_ts = event.get("thread_ts")
        else:
            thread_ts = event.get("thread_ts") or ts

        # In channels, only respond if bot is mentioned
        if not is_dm and self._bot_user_id:
            if f"<@{self._bot_user_id}>" not in text:
                return
            # Strip the bot mention
            text = text.replace(f"<@{self._bot_user_id}>", "").strip()

        if not text.strip():
            return

        if not self._is_allowed(user_id, channel_id):
            logger.debug("Slack: ignoring message from unauthorized user/channel %s/%s", user_id, channel_id)
            return

        user_name = await self._resolve_user_name(user_id)
        source = self._build_source(user_id, user_name, channel_id, channel_type, thread_ts)

        msg = GatewayMessage(
            text=text,
            sender_id=user_id,
            chat_id=channel_id,
            platform="slack",
            sender_name=user_name,
            metadata={
                "source": source,
                "thread_ts": thread_ts,
                "ts": ts,
                "chat_type": source.chat_type,
            },
        )

        if self.on_message:
            try:
                response = await self.on_message(msg)
                if response:
                    await self.send_long_message(
                        channel_id, response,
                        thread_ts=thread_ts,
                    )
                else:
                    await self.send_message(
                        channel_id, "(no response)",
                        thread_ts=thread_ts,
                    )
            except Exception as e:
                logger.error("Slack: error processing message: %s", e, exc_info=True)
                await self.send_message(
                    channel_id,
                    "Sorry, something went wrong processing your message.",
                    thread_ts=thread_ts,
                )

    async def send_message(self, chat_id: str, text: str, **kwargs) -> None:
        """Send a message to a Slack channel."""
        if not self._app:
            return

        send_kwargs = {"channel": chat_id, "text": text}

        thread_ts = kwargs.get("thread_ts")
        if thread_ts:
            send_kwargs["thread_ts"] = thread_ts

        await self._app.client.chat_postMessage(**send_kwargs)

    async def start(self) -> None:
        """Start the Slack bot with Socket Mode."""
        if not self.config.bot_token:
            raise ValueError("Slack bot token (xoxb-...) not configured")
        if not self.config.app_token:
            raise ValueError("Slack app token (xapp-...) not configured")

        self._app = AsyncApp(token=self.config.bot_token)

        # Get bot's own user ID
        auth_response = await self._app.client.auth_test()
        self._bot_user_id = auth_response.get("user_id")
        bot_name = auth_response.get("user", "unknown")

        # Register message handler
        @self._app.event("message")
        async def handle_message(event, say):
            await self._handle_message_event(event)

        # Acknowledge app_mention to prevent Bolt 404 errors
        @self._app.event("app_mention")
        async def handle_app_mention(event, say):
            pass

        # Start Socket Mode
        self._handler = AsyncSocketModeHandler(self._app, self.config.app_token)
        await self._handler.start_async()
        self._running = True

        logger.info("Slack adapter started: @%s (Socket Mode)", bot_name)

    async def stop(self) -> None:
        """Stop the Slack bot."""
        if self._handler:
            try:
                await self._handler.close_async()
            except Exception as e:
                logger.warning("Slack: error closing Socket Mode handler: %s", e)
        self._running = False
        logger.info("Slack adapter stopped")
