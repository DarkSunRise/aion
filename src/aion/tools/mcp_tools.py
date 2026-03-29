"""
In-process MCP tools — expose Aion's memory and sessions to Claude Code.

Uses the SDK's @tool decorator to create thin async wrappers around
MemoryStore and SessionDB. Tools are bound to live instances via the
create_aion_tools() factory closure.
"""

import json
import time
from datetime import datetime
from typing import List

from claude_agent_sdk import tool, SdkMcpTool, Annotated

from aion.memory.store import MemoryStore
from aion.memory.sessions import SessionDB


def _format_age(started_at: float) -> str:
    """Human-readable age from a Unix timestamp."""
    delta = time.time() - started_at
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _format_timestamp(ts: float) -> str:
    """Format a Unix timestamp as a readable date string."""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _text(text: str) -> dict:
    """Standard MCP text response."""
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict:
    """Standard MCP error response."""
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def create_aion_tools(
    memory: MemoryStore, sessions: SessionDB
) -> List[SdkMcpTool]:
    """Create MCP tools bound to Aion's memory and session stores.

    Returns a list of SdkMcpTool instances ready for create_sdk_mcp_server().
    """

    # ── Memory tools ──

    @tool(
        "aion_memory_read",
        "Read Aion's persistent memory (survives across sessions). "
        "Target is 'memory' (agent notes) or 'user' (user profile).",
        {"target": Annotated[str, "'memory' or 'user'"]},
    )
    async def memory_read(args: dict) -> dict:
        target = args["target"]
        if target not in ("memory", "user"):
            return _error("Target must be 'memory' or 'user'.")
        content = memory.snapshot.get(target, "")
        if not content:
            return _text(f"No {target} memory entries.")
        return _text(content)

    @tool(
        "aion_memory_add",
        "Add an entry to persistent memory. "
        "Use 'memory' for agent notes, 'user' for user profile.",
        {
            "target": Annotated[str, "'memory' or 'user'"],
            "content": Annotated[str, "The entry text to add"],
        },
    )
    async def memory_add(args: dict) -> dict:
        target = args["target"]
        if target not in ("memory", "user"):
            return _error("Target must be 'memory' or 'user'.")
        result = memory.add(target, args["content"])
        return _text(json.dumps(result, ensure_ascii=False))

    @tool(
        "aion_memory_replace",
        "Replace an entry in persistent memory. "
        "old_text identifies the entry to replace (substring match).",
        {
            "target": Annotated[str, "'memory' or 'user'"],
            "old_text": Annotated[str, "Substring that uniquely identifies the entry to replace"],
            "content": Annotated[str, "The new entry text"],
        },
    )
    async def memory_replace(args: dict) -> dict:
        target = args["target"]
        if target not in ("memory", "user"):
            return _error("Target must be 'memory' or 'user'.")
        result = memory.replace(target, args["old_text"], args["content"])
        return _text(json.dumps(result, ensure_ascii=False))

    @tool(
        "aion_memory_remove",
        "Remove an entry from persistent memory. "
        "old_text identifies the entry to remove (substring match).",
        {
            "target": Annotated[str, "'memory' or 'user'"],
            "old_text": Annotated[str, "Substring that uniquely identifies the entry to remove"],
        },
    )
    async def memory_remove(args: dict) -> dict:
        target = args["target"]
        if target not in ("memory", "user"):
            return _error("Target must be 'memory' or 'user'.")
        result = memory.remove(target, args["old_text"])
        return _text(json.dumps(result, ensure_ascii=False))

    # ── Session tools ──

    @tool(
        "aion_sessions_list",
        "List recent Aion sessions with titles, sources, ages, and message counts.",
        {"limit": Annotated[int, "Max number of sessions to return (default 10, max 50)"]},
    )
    async def sessions_list(args: dict) -> dict:
        limit = min(max(args.get("limit", 10), 1), 50)
        rows = sessions.list_sessions_rich(limit=limit)

        if not rows:
            return _text("No sessions found.")

        lines = []
        for s in rows:
            # Skip child sessions (compaction fragments)
            if s.get("parent_session_id"):
                continue
            sid = s["id"][:8]
            title = s.get("title") or s.get("preview") or "(untitled)"
            source = s.get("source", "?")
            age = _format_age(s["started_at"]) if s.get("started_at") else "?"
            msgs = s.get("message_count", 0)
            lines.append(f"  {sid}  {title:<40} {source:<10} {age:<10} {msgs} msgs")

        header = f"{'ID':<10} {'Title':<40} {'Source':<10} {'Age':<10} Messages"
        return _text(f"{header}\n{'─' * 80}\n" + "\n".join(lines))

    @tool(
        "aion_sessions_search",
        "Search past Aion sessions by keyword. Returns matching messages with context.",
        {
            "query": Annotated[str, "Search query (FTS5 syntax supported)"],
            "limit": Annotated[int, "Max number of results (default 10, max 50)"],
        },
    )
    async def sessions_search(args: dict) -> dict:
        query = args.get("query", "").strip()
        if not query:
            return _error("Query cannot be empty.")
        limit = min(max(args.get("limit", 10), 1), 50)

        results = sessions.search(query, limit=limit)
        if not results:
            return _text(f"No results for '{query}'.")

        lines = []
        for r in results:
            sid = r["session_id"][:8]
            role = r.get("role", "?")
            snippet = r.get("snippet", r.get("content", "")[:100])
            source = r.get("source", "?")
            when = _format_timestamp(r["started_at"]) if r.get("started_at") else "?"
            lines.append(f"  [{sid}] ({source}, {when}) {role}: {snippet}")

        return _text(f"Found {len(results)} matches for '{query}':\n\n" + "\n".join(lines))

    @tool(
        "aion_session_messages",
        "Get the full conversation from a specific session by ID (or prefix).",
        {"session_id": Annotated[str, "Session ID or unique prefix (at least 8 chars)"]},
    )
    async def session_messages(args: dict) -> dict:
        sid_input = args["session_id"].strip()
        if not sid_input:
            return _error("Session ID cannot be empty.")

        resolved = sessions.resolve_session_id(sid_input)
        if not resolved:
            return _error(
                f"No session found matching '{sid_input}'. "
                "Use aion_sessions_list to see available sessions."
            )

        messages = sessions.get_session_messages(resolved)
        if not messages:
            return _text(f"Session {resolved[:8]} has no messages.")

        session = sessions.get_session(resolved)
        header_parts = [f"Session: {resolved[:8]}"]
        if session:
            if session.get("title"):
                header_parts.append(f"Title: {session['title']}")
            if session.get("source"):
                header_parts.append(f"Source: {session['source']}")
            if session.get("started_at"):
                header_parts.append(f"Started: {_format_timestamp(session['started_at'])}")

        lines = [" | ".join(header_parts), "─" * 60]
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content") or ""
            tool_name = msg.get("tool_name")
            if tool_name:
                lines.append(f"[TOOL:{tool_name}]: {content[:500]}")
            else:
                lines.append(f"[{role}]: {content}")

        return _text("\n".join(lines))

    return [
        memory_read, memory_add, memory_replace, memory_remove,
        sessions_list, sessions_search, session_messages,
    ]
