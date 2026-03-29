"""
Core agent — thin orchestration layer around claude-agent-sdk.

Responsibilities:
1. Build options (memory injection, tool config, MCP servers)
2. Call claude_agent_sdk.query()
3. Stream results back to caller
4. Track session in SQLite
5. Handle memory tool calls intercepted from the stream
"""

import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    query, ClaudeAgentOptions,
    SystemMessage, AssistantMessage, UserMessage, ResultMessage,
    RateLimitEvent,
)

from .config import AionConfig
from .hooks import AionHooks, NotifyCallback
from .memory.store import MemoryStore
from .memory.sessions import SessionDB
from .redact import redact_secrets
from .tools.server import create_aion_mcp_server

logger = logging.getLogger(__name__)


class AionAgent:
    """
    Wraps claude-agent-sdk with memory injection and session tracking.

    Usage:
        agent = AionAgent(config)
        async for msg in agent.run("write a haiku", source="cli"):
            print(msg)
    """

    def __init__(
        self,
        config: AionConfig,
        notify_callback: Optional[NotifyCallback] = None,
    ):
        self.config = config

        # Memory
        self.memory = MemoryStore(
            memory_dir=config.aion_home / "memories",
            memory_char_limit=config.memory.char_limit,
            user_char_limit=config.memory.user_char_limit,
        )
        self.memory.load()

        # Session DB
        self.sessions = SessionDB(config.aion_home / "state.db")
        self.sessions.connect()

        # In-process MCP server (memory + session tools)
        self._aion_mcp = create_aion_mcp_server(self.memory, self.sessions)

        # SDK lifecycle hooks
        self._hooks = AionHooks(notify_callback=notify_callback)

    async def run(
        self,
        prompt: str,
        source: str = "cli",
        user_id: Optional[str] = None,
        cwd: Optional[str] = None,
        resume_session_id: Optional[str] = None,
        max_turns: Optional[int] = None,
        mcp_servers: Optional[dict] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """
        Run a conversation turn. Yields message dicts as they stream from the SDK.

        Args:
            prompt: User's message
            source: Platform source (cli, telegram, discord, etc.)
            user_id: Platform-specific user ID
            cwd: Working directory for the agent
            resume_session_id: Aion session ID to resume (looks up CC session ID)
            max_turns: Override max turns
            mcp_servers: Additional MCP servers to connect
            model: Override model (takes precedence over config.model)
        """
        session_id = str(uuid.uuid4())
        effective_model = model or self.config.model
        self.sessions.create_session(session_id, source, effective_model, user_id)
        self.sessions.add_message(session_id, "user", prompt)

        # Build system prompt with CC preset + memory append
        memory_block = self.memory.system_prompt_block()
        system_prompt = {
            "type": "preset",
            "preset": "claude_code",
            "append": memory_block,
        } if memory_block else {
            "type": "preset",
            "preset": "claude_code",
        }

        # Resolve CC session ID for resume
        cc_session_id = None
        if resume_session_id:
            cc_session_id = self.sessions.get_cc_session_id(resume_session_id)

        # Build options
        try:
            hooks_dict = self._hooks.build_hooks_dict()
        except Exception as e:
            logger.warning("Failed to build hooks, running without: %s", e)
            hooks_dict = None

        options = ClaudeAgentOptions(
            max_turns=max_turns or self.config.max_turns,
            system_prompt=system_prompt,
            permission_mode=self.config.permission_mode,
            cwd=cwd or str(Path.cwd()),
            model=effective_model,
            hooks=hooks_dict,
        )

        # Resume existing CC session
        if cc_session_id:
            options.resume = cc_session_id

        # MCP servers: aion tools + external from config + caller-provided
        mcp = {"aion": self._aion_mcp}
        for name, server_cfg in self.config.mcp_servers.items():
            mcp[name] = server_cfg
        if mcp_servers:
            mcp.update(mcp_servers)
        options.mcp_servers = mcp

        # Stream from SDK
        result_text = ""
        result_session_id = None
        cost_usd = None
        stop_reason = None
        usage = {}

        try:
            async for message in query(prompt=prompt, options=options):
                msg_dict = self._message_to_dict(message)

                # Track system init for CC session ID
                if msg_dict.get("type") == "system":
                    if msg_dict.get("subtype") == "init":
                        result_session_id = msg_dict.get("session_id")
                    elif msg_dict.get("subtype") == "compact_boundary":
                        logger.info(
                            "Context compaction in session %s (cc=%s)",
                            session_id, result_session_id,
                        )
                        # Create child session linked to parent
                        child_id = str(uuid.uuid4())
                        self.sessions.create_session(
                            child_id, source, effective_model, user_id,
                            parent_session_id=session_id,
                        )

                # Track result metadata
                if msg_dict.get("type") == "result":
                    result_text = msg_dict.get("result", "")
                    # Prefer session_id from result, fallback to init
                    if msg_dict.get("session_id"):
                        result_session_id = msg_dict["session_id"]
                    cost_usd = msg_dict.get("cost_usd")
                    stop_reason = msg_dict.get("stop_reason")
                    usage = msg_dict.get("usage", {})

                # Log rate limit events
                if msg_dict.get("type") == "rate_limit_event":
                    info = msg_dict.get("rate_limit_info", {})
                    if info.get("status") != "allowed":
                        logger.warning(
                            "Rate limit: status=%s (resets at %s)",
                            info.get("status", "?"),
                            info.get("resets_at", "unknown"),
                        )

                # Redact secrets if audit enabled
                if self.config.audit.redact_secrets and "content" in msg_dict:
                    msg_dict["content"] = redact_secrets(msg_dict["content"])

                yield msg_dict

        except Exception as e:
            logger.error("Agent SDK error: %s", e)
            stop_reason = "error"
            yield {"type": "error", "error": str(e)}

        finally:
            # Store assistant response
            if result_text:
                self.sessions.add_message(session_id, "assistant", result_text)

            # Log usage details
            if usage:
                logger.info(
                    "Session %s usage: %s, cost=$%.4f",
                    session_id[:8], usage, cost_usd or 0,
                )

            # End session with CC session ID for future resume
            self.sessions.end_session(
                session_id,
                cc_session_id=result_session_id,
                cost_usd=cost_usd,
                end_reason=stop_reason,
            )

    async def continue_session(
        self,
        prompt: str,
        cc_session_id: str,
        source: str = "cli",
        user_id: Optional[str] = None,
        cwd: Optional[str] = None,
        max_turns: Optional[int] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Continue an existing CC session.

        Uses resume=cc_session_id to pick up where the previous session left off.
        This is for within-process continuation — the CC SDK maintains the
        conversation context from the previous session.
        """
        session_id = str(uuid.uuid4())
        effective_model = model or self.config.model
        self.sessions.create_session(session_id, source, effective_model, user_id)
        self.sessions.add_message(session_id, "user", prompt)

        # Build options with resume
        memory_block = self.memory.system_prompt_block()
        system_prompt = {
            "type": "preset",
            "preset": "claude_code",
            "append": memory_block,
        } if memory_block else {
            "type": "preset",
            "preset": "claude_code",
        }

        try:
            hooks_dict = self._hooks.build_hooks_dict()
        except Exception as e:
            logger.warning("Failed to build hooks, running without: %s", e)
            hooks_dict = None

        options = ClaudeAgentOptions(
            max_turns=max_turns or self.config.max_turns,
            system_prompt=system_prompt,
            permission_mode=self.config.permission_mode,
            cwd=cwd or str(Path.cwd()),
            model=effective_model,
            resume=cc_session_id,
            hooks=hooks_dict,
        )

        # MCP servers: aion tools + external from config
        mcp = {"aion": self._aion_mcp}
        for name, server_cfg in self.config.mcp_servers.items():
            mcp[name] = server_cfg
        options.mcp_servers = mcp

        result_text = ""
        new_cc_session_id = None
        cost_usd = None
        stop_reason = None

        try:
            async for message in query(prompt=prompt, options=options):
                msg_dict = self._message_to_dict(message)

                if msg_dict.get("type") == "system" and msg_dict.get("subtype") == "init":
                    new_cc_session_id = msg_dict.get("session_id")

                if msg_dict.get("type") == "result":
                    result_text = msg_dict.get("result", "")
                    if msg_dict.get("session_id"):
                        new_cc_session_id = msg_dict["session_id"]
                    cost_usd = msg_dict.get("cost_usd")
                    stop_reason = msg_dict.get("stop_reason")

                if self.config.audit.redact_secrets and "content" in msg_dict:
                    msg_dict["content"] = redact_secrets(msg_dict["content"])

                yield msg_dict

        except Exception as e:
            logger.error("Agent SDK error (continue): %s", e)
            stop_reason = "error"
            yield {"type": "error", "error": str(e)}

        finally:
            if result_text:
                self.sessions.add_message(session_id, "assistant", result_text)

            self.sessions.end_session(
                session_id,
                cc_session_id=new_cc_session_id or cc_session_id,
                cost_usd=cost_usd,
                end_reason=stop_reason,
            )

    def _message_to_dict(self, message) -> dict:
        """Convert SDK message to a plain dict.

        Uses isinstance checks — SDK messages are typed classes, not dicts:
        - SystemMessage: .subtype, .data (dict with session_id, model, tools)
        - AssistantMessage: .content (list of TextBlock/ToolUseBlock/ThinkingBlock)
        - UserMessage: .content (list of ToolResultBlock)
        - ResultMessage: .result, .total_cost_usd, .num_turns, .session_id, etc.
        - RateLimitEvent: .rate_limit_info
        """
        if isinstance(message, SystemMessage):
            data = getattr(message, "data", {}) or {}
            subtype = getattr(message, "subtype", None)
            result = {"type": "system", "subtype": subtype}
            if subtype == "init":
                result["session_id"] = data.get("session_id")
                result["model"] = data.get("model")
                result["tools"] = data.get("tools", [])
            return result

        if isinstance(message, AssistantMessage):
            result = {"type": "assistant"}
            content_parts = []
            tool_uses = []
            thinking = []
            for block in getattr(message, "content", []):
                block_type = type(block).__name__
                if block_type == "ThinkingBlock" or hasattr(block, "thinking"):
                    thinking.append(getattr(block, "thinking", str(block)))
                elif block_type == "TextBlock" or hasattr(block, "text"):
                    content_parts.append(block.text)
                elif block_type == "ToolUseBlock" or hasattr(block, "name"):
                    tool_uses.append({
                        "name": block.name,
                        "input": getattr(block, "input", {}),
                        "id": getattr(block, "id", None),
                    })
            if content_parts:
                result["content"] = "\n".join(content_parts)
            if tool_uses:
                result["tool_uses"] = tool_uses
            if thinking:
                result["thinking"] = thinking
            return result

        if isinstance(message, UserMessage):
            result = {"type": "user"}
            tool_results = []
            for block in getattr(message, "content", []):
                if hasattr(block, "tool_use_id"):
                    tool_results.append({
                        "tool_use_id": block.tool_use_id,
                        "content": getattr(block, "content", None),
                        "is_error": getattr(block, "is_error", False),
                    })
            if tool_results:
                result["tool_results"] = tool_results
            return result

        if isinstance(message, ResultMessage):
            result = {
                "type": "result",
                "result": getattr(message, "result", ""),
                "subtype": getattr(message, "subtype", None),
                "session_id": getattr(message, "session_id", None),
                "cost_usd": getattr(message, "total_cost_usd", None),
                "num_turns": getattr(message, "num_turns", None),
                "duration_api_ms": getattr(message, "duration_api_ms", None),
                "stop_reason": getattr(message, "stop_reason", None),
                "is_error": getattr(message, "is_error", False),
            }
            raw_usage = getattr(message, "usage", None)
            if raw_usage and isinstance(raw_usage, dict):
                result["usage"] = raw_usage
            elif raw_usage:
                result["usage"] = {
                    "input_tokens": getattr(raw_usage, "input_tokens", 0),
                    "output_tokens": getattr(raw_usage, "output_tokens", 0),
                    "cache_read": getattr(raw_usage, "cache_read_input_tokens", 0),
                    "cache_write": getattr(raw_usage, "cache_creation_input_tokens", 0),
                }
            return result

        if isinstance(message, RateLimitEvent):
            result = {"type": "rate_limit_event"}
            rate_info = getattr(message, "rate_limit_info", None)
            if rate_info:
                result["rate_limit_info"] = {
                    "status": getattr(rate_info, "status", None),
                    "resets_at": getattr(rate_info, "resets_at", None),
                    "utilization": getattr(rate_info, "utilization", None),
                }
            return result

        # Unknown message type — log and pass through
        logger.debug("Unknown SDK message type: %s", type(message).__name__)
        return {"type": "unknown", "class": type(message).__name__}

    def search_sessions(self, query_text: str, limit: int = 3) -> list:
        """Search past conversations."""
        return self.sessions.search(query_text, limit)

    def recent_sessions(self, limit: int = 10) -> list:
        """Get recent sessions."""
        return self.sessions.recent_sessions(limit)
