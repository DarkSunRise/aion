"""
Core agent — thin orchestration layer around claude-agent-sdk.

Responsibilities:
1. Build options (memory injection, tool config, MCP servers)
2. Call claude_agent_sdk.query()
3. Stream results back to caller
4. Track session in SQLite
5. Handle memory tool calls intercepted from the stream
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from claude_agent_sdk import query, ClaudeAgentOptions

from .config import AionConfig
from .memory.store import MemoryStore
from .memory.sessions import SessionDB
from .redact import redact_secrets

logger = logging.getLogger(__name__)


class AionAgent:
    """
    Wraps claude-agent-sdk with memory injection and session tracking.

    Usage:
        agent = AionAgent(config)
        async for msg in agent.run("write a haiku", source="cli"):
            print(msg)
    """

    def __init__(self, config: AionConfig):
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

    async def run(
        self,
        prompt: str,
        source: str = "cli",
        user_id: Optional[str] = None,
        cwd: Optional[str] = None,
        resume_session_id: Optional[str] = None,
        max_turns: Optional[int] = None,
        mcp_servers: Optional[dict] = None,
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
        """
        session_id = str(uuid.uuid4())
        self.sessions.create_session(session_id, source, self.config.model, user_id)
        self.sessions.add_message(session_id, "user", prompt)

        # Build system prompt append with memory
        memory_block = self.memory.system_prompt_block()
        append_prompt = memory_block if memory_block else None

        # Resolve CC session ID for resume
        cc_session_id = None
        if resume_session_id:
            cc_session_id = self.sessions.get_cc_session_id(resume_session_id)

        # Build options
        options = ClaudeAgentOptions(
            max_turns=max_turns or self.config.max_turns,
            append_system_prompt=append_prompt,
            permission_mode=self.config.permission_mode,
            cwd=cwd or str(Path.cwd()),
            session_id=cc_session_id,
        )

        # Add MCP servers if provided
        if mcp_servers:
            options.mcp_servers = mcp_servers

        # Stream from SDK
        result_text = ""
        result_session_id = None
        cost_usd = None

        try:
            async for message in query(prompt=prompt, options=options):
                msg_dict = self._message_to_dict(message)

                # Track result metadata
                if msg_dict.get("type") == "result":
                    result_text = msg_dict.get("result", "")
                    result_session_id = msg_dict.get("session_id")
                    cost_usd = msg_dict.get("cost_usd")

                # Redact secrets if audit enabled
                if self.config.audit.redact_secrets and "content" in msg_dict:
                    msg_dict["content"] = redact_secrets(msg_dict["content"])

                yield msg_dict

        except Exception as e:
            logger.error("Agent SDK error: %s", e)
            yield {"type": "error", "error": str(e)}

        finally:
            # Store assistant response
            if result_text:
                self.sessions.add_message(session_id, "assistant", result_text)

            # End session with CC session ID for future resume
            self.sessions.end_session(
                session_id,
                cc_session_id=result_session_id,
                cost_usd=cost_usd,
            )

    def _message_to_dict(self, message) -> dict:
        """Convert SDK message to a plain dict."""
        result = {"type": getattr(message, "type", "unknown")}

        if hasattr(message, "content"):
            # AssistantMessage
            content_parts = []
            for block in message.content:
                if hasattr(block, "text"):
                    content_parts.append(block.text)
                elif hasattr(block, "name"):
                    result["tool_use"] = {"name": block.name, "input": getattr(block, "input", {})}
            if content_parts:
                result["content"] = "\n".join(content_parts)

        if hasattr(message, "result"):
            # ResultMessage
            result["result"] = message.result
            result["session_id"] = getattr(message, "session_id", None)
            result["cost_usd"] = getattr(message, "cost_usd", None)
            result["num_turns"] = getattr(message, "num_turns", None)
            result["is_error"] = getattr(message, "is_error", False)

        if hasattr(message, "tools"):
            # SystemMessage
            result["tools"] = message.tools

        return result

    def search_sessions(self, query_text: str, limit: int = 3) -> list:
        """Search past conversations."""
        return self.sessions.search(query_text, limit)

    def recent_sessions(self, limit: int = 10) -> list:
        """Get recent sessions."""
        return self.sessions.recent_sessions(limit)
