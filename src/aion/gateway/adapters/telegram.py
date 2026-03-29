"""
Telegram gateway adapter.

Uses python-telegram-bot v20+ (fully async) with polling.
Simplified from Hermes TelegramAdapter (~1900 LOC → ~250 LOC).
"""

import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatType

from ..base import GatewayAdapter, GatewayMessage
from ..config import TelegramConfig
from ..session import SessionSource

logger = logging.getLogger(__name__)


class TelegramAdapter(GatewayAdapter):
    """Telegram bot adapter using long-polling."""

    platform_name = "telegram"
    max_message_length = 4096

    def __init__(self, config: TelegramConfig):
        super().__init__()
        self.config = config
        self._app: Optional[Application] = None

    def _is_allowed(self, user_id: int) -> bool:
        """Check if a user is in the allowlist (empty = allow all)."""
        if not self.config.allowed_users:
            return True
        return str(user_id) in self.config.allowed_users

    def _build_source(self, update: Update) -> SessionSource:
        """Build a SessionSource from a Telegram Update."""
        user = update.effective_user
        chat = update.effective_chat

        if chat.type == ChatType.PRIVATE:
            chat_type = "dm"
        elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            chat_type = "group"
        elif chat.type == ChatType.CHANNEL:
            chat_type = "channel"
        else:
            chat_type = "dm"

        return SessionSource(
            platform="telegram",
            user_id=str(user.id) if user else "",
            user_name=user.full_name if user else None,
            chat_id=str(chat.id) if chat else "",
            chat_type=chat_type,
            chat_name=chat.title if chat and chat.title else None,
        )

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        if not update.effective_user or not update.effective_chat:
            return

        if not self._is_allowed(update.effective_user.id):
            return

        name = update.effective_user.first_name or "there"
        await update.effective_chat.send_message(
            f"Hello {name}! I'm Aion. Send me a message and I'll respond."
        )

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming text messages."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return

        text = update.message.text or update.message.caption or ""
        if not text.strip():
            return

        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            logger.debug("Telegram: ignoring message from unauthorized user %s", user_id)
            return

        # In groups, only respond if bot is mentioned
        chat = update.effective_chat
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            bot_user = context.bot
            if bot_user and bot_user.username:
                mention = f"@{bot_user.username}"
                if mention not in text:
                    return
                text = text.replace(mention, "").strip()

        if not text:
            return

        # Send typing indicator
        await update.effective_chat.send_action("typing")

        source = self._build_source(update)

        msg = GatewayMessage(
            text=text,
            sender_id=str(user_id),
            chat_id=str(chat.id),
            platform="telegram",
            sender_name=update.effective_user.full_name,
            reply_to=str(update.message.message_id),
            metadata={
                "source": source,
                "chat_type": source.chat_type,
            },
        )

        if self.on_message:
            try:
                response = await self.on_message(msg)
                if response:
                    await self.send_long_message(
                        str(chat.id), response,
                        reply_to_message_id=update.message.message_id,
                    )
                else:
                    await update.effective_chat.send_message("(no response)")
            except Exception as e:
                logger.error("Telegram: error processing message: %s", e, exc_info=True)
                await update.effective_chat.send_message(
                    "Sorry, something went wrong processing your message."
                )

    async def send_message(self, chat_id: str, text: str, **kwargs) -> None:
        """Send a message to a Telegram chat."""
        if not self._app:
            return

        send_kwargs = {"chat_id": int(chat_id), "text": text}

        # Reply to specific message if provided
        reply_to = kwargs.get("reply_to_message_id")
        if reply_to:
            send_kwargs["reply_to_message_id"] = int(reply_to)

        await self._app.bot.send_message(**send_kwargs)

    async def start(self) -> None:
        """Start the Telegram bot with polling."""
        if not self.config.token:
            raise ValueError("Telegram bot token not configured")

        self._app = (
            Application.builder()
            .token(self.config.token)
            .build()
        )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self._app.initialize()
        await self._app.start()

        # Start polling in the background
        await self._app.updater.start_polling(drop_pending_updates=True)
        self._running = True

        bot_info = await self._app.bot.get_me()
        logger.info(
            "Telegram adapter started: @%s (id=%s)",
            bot_info.username, bot_info.id,
        )

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()
        self._running = False
        logger.info("Telegram adapter stopped")
