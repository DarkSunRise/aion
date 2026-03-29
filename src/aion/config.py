"""
Configuration management for Aion.

Loads from ~/.aion/config.yaml with env var interpolation.
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def get_aion_home() -> Path:
    """Return the Aion home directory, creating it if needed."""
    home = Path(os.environ.get("AION_HOME", Path.home() / ".aion"))
    home.mkdir(parents=True, exist_ok=True)
    return home


DEFAULT_CONFIG = {
    "model": "claude-sonnet-4-20250514",
    "max_turns": 100,
    "permission_mode": "bypassPermissions",
    "memory": {
        "char_limit": 2200,
        "user_char_limit": 1375,
    },
    "gateway": {},
    "auxiliary": None,
    "audit": {
        "enabled": True,
        "log_tool_calls": True,
        "redact_secrets": True,
    },
}


@dataclass
class AuxiliaryConfig:
    """Config for optional non-Anthropic providers (Gemini for vision, etc.)."""
    provider: str = "google"
    model: str = "gemini-2.0-flash"
    api_key: Optional[str] = None


@dataclass
class MemoryConfig:
    char_limit: int = 2200
    user_char_limit: int = 1375


@dataclass
class AuditConfig:
    enabled: bool = True
    log_tool_calls: bool = True
    redact_secrets: bool = True


@dataclass
class AionConfig:
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 100
    permission_mode: str = "bypassPermissions"
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    auxiliary: Optional[AuxiliaryConfig] = None
    gateway: dict = field(default_factory=dict)
    mcp_servers: dict = field(default_factory=dict)  # name -> {command, args, env}

    # Runtime — not from config file
    aion_home: Path = field(default_factory=get_aion_home)


def _interpolate_env(value: str) -> str:
    """Replace ${VAR} with environment variable values."""
    def replacer(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    return re.sub(r'\$\{(\w+)\}', replacer, value)


def _interpolate_dict(d: dict) -> dict:
    """Recursively interpolate env vars in dict values."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _interpolate_env(v)
        elif isinstance(v, dict):
            result[k] = _interpolate_dict(v)
        else:
            result[k] = v
    return result


def load_config(config_path: Optional[Path] = None) -> AionConfig:
    """Load config from YAML, merge with defaults, interpolate env vars."""
    aion_home = get_aion_home()

    if config_path is None:
        config_path = aion_home / "config.yaml"

    raw = dict(DEFAULT_CONFIG)

    if config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        user_config = _interpolate_dict(user_config)
        raw.update(user_config)

    # Build config object
    memory_raw = raw.get("memory", {})
    memory = MemoryConfig(
        char_limit=memory_raw.get("char_limit", 2200),
        user_char_limit=memory_raw.get("user_char_limit", 1375),
    )

    audit_raw = raw.get("audit", {})
    audit = AuditConfig(
        enabled=audit_raw.get("enabled", True),
        log_tool_calls=audit_raw.get("log_tool_calls", True),
        redact_secrets=audit_raw.get("redact_secrets", True),
    )

    auxiliary = None
    aux_raw = raw.get("auxiliary")
    if aux_raw and isinstance(aux_raw, dict):
        auxiliary = AuxiliaryConfig(
            provider=aux_raw.get("provider", "google"),
            model=aux_raw.get("model", "gemini-2.0-flash"),
            api_key=aux_raw.get("api_key"),
        )

    # Parse mcp_servers — interpolate env vars in each server config
    mcp_servers_raw = raw.get("mcp_servers", {})
    mcp_servers = {}
    if isinstance(mcp_servers_raw, dict):
        for name, server_cfg in mcp_servers_raw.items():
            if isinstance(server_cfg, dict):
                mcp_servers[name] = _interpolate_dict(server_cfg)

    return AionConfig(
        model=raw.get("model", "claude-sonnet-4-20250514"),
        max_turns=raw.get("max_turns", 100),
        permission_mode=raw.get("permission_mode", "bypassPermissions"),
        memory=memory,
        audit=audit,
        auxiliary=auxiliary,
        gateway=raw.get("gateway", {}),
        mcp_servers=mcp_servers,
        aion_home=aion_home,
    )
