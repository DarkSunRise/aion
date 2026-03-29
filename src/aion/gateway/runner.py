"""
Gateway runner — starts configured adapters and wires message handling.

Loads GatewayConfig, instantiates adapters, connects the on_message
callback (message → agent.run() → send response), and handles
graceful shutdown on SIGINT/SIGTERM.
"""

import asyncio
import logging
import signal
from typing import Optional

from ..agent import AionAgent
from ..config import AionConfig, load_config
from ..utils.ansi import strip_ansi

from .base import GatewayAdapter, GatewayMessage
from .config import GatewayConfig
from .session import SessionSource, build_session_context_prompt

logger = logging.getLogger(__name__)


class GatewayRunner:
    """Manages the lifecycle of all gateway adapters."""

    def __init__(self, config: AionConfig):
        self.config = config
        self.gateway_config = GatewayConfig.from_dict(config.gateway)
        self.adapters: list[GatewayAdapter] = []
        self._agent: Optional[AionAgent] = None
        self._shutdown_event = asyncio.Event()

    def _create_agent(self) -> AionAgent:
        """Create the shared AionAgent instance."""
        if self._agent is None:
            self._agent = AionAgent(self.config)
        return self._agent

    async def _handle_message(self, msg: GatewayMessage) -> str:
        """Process an incoming message through the agent.

        Called by each adapter's on_message callback.
        Returns the agent's response text.
        """
        agent = self._create_agent()

        # Build session context prompt
        source = msg.metadata.get("source")
        if not isinstance(source, SessionSource):
            source = SessionSource(
                platform=msg.platform,
                user_id=msg.sender_id,
                user_name=msg.sender_name,
                chat_id=msg.chat_id,
            )

        context_prompt = build_session_context_prompt(
            source,
            connected_platforms=self.gateway_config.connected_platforms,
        )

        # Build system prompt: preset + memory + session context
        memory_block = agent.memory.system_prompt_block()
        append_parts = []
        if memory_block:
            append_parts.append(memory_block)
        append_parts.append(context_prompt)
        append_text = "\n\n".join(append_parts)

        # Collect the final result text from the agent stream
        result_text = ""

        async for msg_dict in agent.run(
            prompt=msg.text,
            source=msg.platform,
            user_id=msg.sender_id,
        ):
            if msg_dict.get("type") == "result":
                result_text = msg_dict.get("result", "")

        # Strip ANSI escape codes from CC output
        if result_text:
            result_text = strip_ansi(result_text)

        return result_text

    def _setup_adapters(self) -> None:
        """Instantiate adapters based on config."""
        gc = self.gateway_config

        if gc.telegram and gc.telegram.token:
            from .adapters.telegram import TelegramAdapter
            adapter = TelegramAdapter(gc.telegram)
            adapter.on_message = self._handle_message
            self.adapters.append(adapter)
            logger.info("Telegram adapter configured")

        if gc.slack and gc.slack.bot_token:
            from .adapters.slack import SlackAdapter
            adapter = SlackAdapter(gc.slack)
            adapter.on_message = self._handle_message
            self.adapters.append(adapter)
            logger.info("Slack adapter configured")

    async def _start_adapters(self) -> None:
        """Start all configured adapters."""
        for adapter in self.adapters:
            try:
                await adapter.start()
            except Exception as e:
                logger.error(
                    "Failed to start %s adapter: %s",
                    adapter.platform_name, e, exc_info=True,
                )

    async def _stop_adapters(self) -> None:
        """Stop all running adapters."""
        for adapter in self.adapters:
            if adapter.is_running:
                try:
                    await adapter.stop()
                except Exception as e:
                    logger.warning(
                        "Error stopping %s adapter: %s",
                        adapter.platform_name, e,
                    )

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def run(self) -> None:
        """Start all adapters and block until shutdown."""
        self._setup_adapters()

        if not self.adapters:
            logger.error(
                "No gateway adapters configured. "
                "Add telegram or slack config to ~/.aion/config.yaml"
            )
            return

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)

        # Start all adapters
        await self._start_adapters()

        running = [a for a in self.adapters if a.is_running]
        if not running:
            logger.error("No adapters started successfully")
            return

        platform_names = [a.platform_name for a in running]
        logger.info("Gateway running: %s", ", ".join(platform_names))
        print(f"Aion gateway running: {', '.join(platform_names)}")
        print("Press Ctrl+C to stop")

        # Block until shutdown signal
        await self._shutdown_event.wait()

        print("\nShutting down...")
        await self._stop_adapters()
        logger.info("Gateway stopped")


async def start_gateway(config: Optional[AionConfig] = None) -> None:
    """Entry point for starting the gateway."""
    if config is None:
        config = load_config()

    runner = GatewayRunner(config)
    await runner.run()
