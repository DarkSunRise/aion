"""
Gateway configuration — platform-specific settings.

Loaded from ~/.aion/config.yaml under the `gateway:` key.
Supports env var interpolation for tokens (${VAR}).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional


def _interpolate_env(value: str) -> str:
    """Replace ${VAR} with environment variable values."""
    def replacer(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    return re.sub(r'\$\{(\w+)\}', replacer, value)


@dataclass
class TelegramConfig:
    """Telegram bot configuration."""

    token: str = ""
    allowed_users: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "TelegramConfig":
        token = data.get("token", "")
        if isinstance(token, str):
            token = _interpolate_env(token)
        allowed = data.get("allowed_users", [])
        return cls(
            token=token,
            allowed_users=[str(u) for u in allowed],
        )


@dataclass
class SlackConfig:
    """Slack bot configuration (Socket Mode)."""

    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-...
    allowed_users: list[str] = field(default_factory=list)
    allowed_channels: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SlackConfig":
        bot_token = data.get("bot_token", "")
        app_token = data.get("app_token", "")
        if isinstance(bot_token, str):
            bot_token = _interpolate_env(bot_token)
        if isinstance(app_token, str):
            app_token = _interpolate_env(app_token)
        return cls(
            bot_token=bot_token,
            app_token=app_token,
            allowed_users=[str(u) for u in data.get("allowed_users", [])],
            allowed_channels=[str(c) for c in data.get("allowed_channels", [])],
        )


@dataclass
class GatewayConfig:
    """Top-level gateway configuration."""

    telegram: Optional[TelegramConfig] = None
    slack: Optional[SlackConfig] = None

    @classmethod
    def from_dict(cls, data: dict) -> "GatewayConfig":
        telegram = None
        slack = None

        tg_data = data.get("telegram")
        if tg_data and isinstance(tg_data, dict):
            telegram = TelegramConfig.from_dict(tg_data)

        sl_data = data.get("slack")
        if sl_data and isinstance(sl_data, dict):
            slack = SlackConfig.from_dict(sl_data)

        return cls(telegram=telegram, slack=slack)

    @property
    def has_any(self) -> bool:
        """Return True if at least one platform is configured."""
        return self.telegram is not None or self.slack is not None

    @property
    def connected_platforms(self) -> list[str]:
        """List of configured platform names."""
        platforms = []
        if self.telegram and self.telegram.token:
            platforms.append("telegram")
        if self.slack and self.slack.bot_token:
            platforms.append("slack")
        return platforms
