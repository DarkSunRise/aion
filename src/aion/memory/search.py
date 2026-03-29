"""
LLM-powered session search — long-term conversation recall.

Searches past session transcripts via FTS5, then summarizes the top
matching sessions using a cheap LLM call (aion.llm.complete).
Returns focused summaries rather than raw transcripts.

Flow:
  1. FTS5 search finds matching messages ranked by relevance
  2. Groups by session, takes top N unique sessions
  3. Loads each session's conversation, truncates around matches
  4. Summarizes via aion.llm.complete()
  5. Returns per-session summaries with metadata
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from aion.memory.sessions import SessionDB

logger = logging.getLogger(__name__)

MAX_SESSION_CHARS = 100_000


def _format_timestamp(ts: Union[int, float, str, None]) -> str:
    """Convert a Unix timestamp to a human-readable date."""
    if ts is None:
        return "unknown"
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
            return dt.strftime("%B %d, %Y at %I:%M %p")
        if isinstance(ts, str):
            if ts.replace(".", "").replace("-", "").isdigit():
                dt = datetime.fromtimestamp(float(ts))
                return dt.strftime("%B %d, %Y at %I:%M %p")
            return ts
    except (ValueError, OSError, OverflowError):
        pass
    return str(ts)


def _format_conversation(messages: List[Dict[str, Any]]) -> str:
    """Format session messages into a readable transcript for summarization."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content") or ""
        tool_name = msg.get("tool_name")

        if role == "TOOL" and tool_name:
            if len(content) > 500:
                content = content[:250] + "\n...[truncated]...\n" + content[-250:]
            parts.append(f"[TOOL:{tool_name}]: {content}")
        elif role == "ASSISTANT":
            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                tc_names = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        name = tc.get("name") or tc.get("function", {}).get("name", "?")
                        tc_names.append(name)
                if tc_names:
                    parts.append(f"[ASSISTANT]: [Called: {', '.join(tc_names)}]")
                if content:
                    parts.append(f"[ASSISTANT]: {content}")
            else:
                parts.append(f"[{role}]: {content}")
        else:
            parts.append(f"[{role}]: {content}")

    return "\n\n".join(parts)


def _truncate_around_matches(
    full_text: str, query: str, max_chars: int = MAX_SESSION_CHARS
) -> str:
    """Truncate a transcript to max_chars, centered around query term matches."""
    if len(full_text) <= max_chars:
        return full_text

    query_terms = query.lower().split()
    text_lower = full_text.lower()
    first_match = len(full_text)
    for term in query_terms:
        pos = text_lower.find(term)
        if pos != -1 and pos < first_match:
            first_match = pos

    if first_match == len(full_text):
        first_match = 0

    half = max_chars // 2
    start = max(0, first_match - half)
    end = min(len(full_text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)

    truncated = full_text[start:end]
    prefix = "...[earlier conversation truncated]...\n\n" if start > 0 else ""
    suffix = "\n\n...[later conversation truncated]..." if end < len(full_text) else ""
    return prefix + truncated + suffix


async def _summarize_session(
    conversation_text: str, query: str, session_meta: Dict[str, Any]
) -> Optional["SessionSummary"]:
    """Summarize a single session conversation focused on the search query."""
    from aion.llm import complete_structured
    from aion.schemas import SessionSummary

    system_prompt = (
        "You are reviewing a past conversation transcript to help recall what happened. "
        "Summarize the conversation with a focus on the search topic. Include:\n"
        "1. What the user asked about or wanted to accomplish\n"
        "2. What actions were taken and what the outcomes were\n"
        "3. Key decisions, solutions found, or conclusions reached\n"
        "4. Any specific commands, files, URLs, or technical details that were important\n"
        "5. Anything left unresolved or notable\n\n"
        "Be thorough but concise. Preserve specific details (commands, paths, error messages) "
        "that would be useful to recall. Write in past tense as a factual recap.\n\n"
        "Rate relevance to the search topic from 0.0 (unrelated) to 1.0 (directly about it)."
    )

    source = session_meta.get("source", "unknown")
    started = _format_timestamp(session_meta.get("started_at"))

    prompt = (
        f"Search topic: {query}\n"
        f"Session source: {source}\n"
        f"Session date: {started}\n\n"
        f"CONVERSATION TRANSCRIPT:\n{conversation_text}\n\n"
        f"Summarize this conversation with focus on: {query}"
    )

    return await complete_structured(prompt, SessionSummary, system=system_prompt)


def _resolve_to_parent(db: SessionDB, session_id: str) -> str:
    """Walk parent chain to find the root session ID."""
    visited = set()
    sid = session_id
    while sid and sid not in visited:
        visited.add(sid)
        session = db.get_session(sid)
        if not session:
            break
        parent = session.get("parent_session_id")
        if parent:
            sid = parent
        else:
            break
    return sid


def _list_recent_sessions(
    db: SessionDB, limit: int, current_session_id: Optional[str] = None
) -> str:
    """Return metadata for the most recent sessions (no LLM calls)."""
    sessions = db.list_sessions_rich(limit=limit + 5)

    # Resolve current session lineage to exclude it
    current_root = None
    if current_session_id:
        try:
            current_root = _resolve_to_parent(db, current_session_id)
        except Exception:
            current_root = current_session_id

    results = []
    for s in sessions:
        sid = s.get("id", "")
        if current_root and (sid == current_root or sid == current_session_id):
            continue
        if s.get("parent_session_id"):
            continue
        results.append({
            "session_id": sid,
            "title": s.get("title"),
            "source": s.get("source", ""),
            "started_at": s.get("started_at", ""),
            "last_active": s.get("last_active", ""),
            "message_count": s.get("message_count", 0),
            "preview": s.get("preview", ""),
        })
        if len(results) >= limit:
            break

    return json.dumps({
        "success": True,
        "mode": "recent",
        "results": results,
        "count": len(results),
        "message": f"Showing {len(results)} most recent sessions.",
    }, ensure_ascii=False)


async def search_sessions(
    db: SessionDB,
    query: str,
    limit: int = 3,
    current_session_id: Optional[str] = None,
) -> str:
    """Search past sessions and return focused summaries.

    Two modes:
    1. No query → recent sessions (no LLM, just formatted list)
    2. With query → FTS5 search + LLM summarization of matches

    The current session is excluded from results.
    """
    limit = min(limit, 5)

    if not query or not query.strip():
        return _list_recent_sessions(db, limit, current_session_id)

    query = query.strip()

    raw_results = db.search_messages(query=query, limit=50, offset=0)

    if not raw_results:
        return json.dumps({
            "success": True,
            "query": query,
            "results": [],
            "count": 0,
            "message": "No matching sessions found.",
        }, ensure_ascii=False)

    # Resolve current session lineage
    current_lineage_root = (
        _resolve_to_parent(db, current_session_id) if current_session_id else None
    )

    # Group by resolved (parent) session_id, dedup, skip current lineage
    seen_sessions = {}
    for result in raw_results:
        raw_sid = result["session_id"]
        resolved_sid = _resolve_to_parent(db, raw_sid)
        if current_lineage_root and resolved_sid == current_lineage_root:
            continue
        if current_session_id and raw_sid == current_session_id:
            continue
        if resolved_sid not in seen_sessions:
            result = dict(result)
            result["session_id"] = resolved_sid
            seen_sessions[resolved_sid] = result
        if len(seen_sessions) >= limit:
            break

    # Prepare sessions for summarization
    tasks = []
    for session_id, match_info in seen_sessions.items():
        try:
            messages = db.get_messages_as_conversation(session_id)
            if not messages:
                continue
            session_meta = db.get_session(session_id) or {}
            conversation_text = _format_conversation(messages)
            conversation_text = _truncate_around_matches(conversation_text, query)
            tasks.append((session_id, match_info, conversation_text, session_meta))
        except Exception as e:
            logger.warning("Failed to prepare session %s: %s", session_id, e)

    # Summarize all sessions in parallel
    coros = [
        _summarize_session(text, query, meta)
        for _, _, text, meta in tasks
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    summaries = []
    for (session_id, match_info, _, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.warning("Failed to summarize session %s: %s", session_id, result)
            continue
        if result:
            summaries.append({
                "session_id": session_id,
                "when": _format_timestamp(match_info.get("session_started")),
                "source": match_info.get("source", "unknown"),
                "title": result.title,
                "summary": result.summary,
                "relevance": result.relevance,
            })

    return json.dumps({
        "success": True,
        "query": query,
        "results": summaries,
        "count": len(summaries),
        "sessions_searched": len(seen_sessions),
    }, ensure_ascii=False)
