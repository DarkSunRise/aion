"""Aion gateway — messaging platform adapters."""

from .base import GatewayAdapter, GatewayMessage, split_message
from .config import GatewayConfig, TelegramConfig, SlackConfig
from .session import SessionSource, build_session_context_prompt
from .runner import GatewayRunner, start_gateway

__all__ = [
    "GatewayAdapter",
    "GatewayMessage",
    "GatewayConfig",
    "TelegramConfig",
    "SlackConfig",
    "SessionSource",
    "build_session_context_prompt",
    "GatewayRunner",
    "start_gateway",
    "split_message",
]
