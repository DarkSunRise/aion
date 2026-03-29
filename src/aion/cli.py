"""
CLI entry point for Aion.

Usage:
    aion "write a haiku"                    # One-shot
    aion                                     # Interactive
    aion --gateway telegram                  # Start gateway
    aion --resume a3f2                       # Resume session by prefix
    aion --continue                          # Resume most recent session
    aion --model claude-opus-4               # Override model
    aion --sessions                          # List recent sessions
    aion --search "auth module"              # Search sessions
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path

from .config import load_config
from .log import configure_logging
from .agent import AionAgent
from .memory.sessions import SessionDB


def _print_message(msg: dict):
    """Print a message dict to stdout.

    Only prints the final result text (from ResultMessage), not intermediate
    assistant messages which contain tool-use chatter like "Let me check...".
    """
    msg_type = msg.get("type", "")

    if msg_type == "result":
        if msg.get("is_error"):
            print(f"\n[ERROR] {msg.get('result', 'Unknown error')}", file=sys.stderr)
        else:
            result_text = msg.get("result", "")
            cost = msg.get("cost_usd")
            turns = msg.get("num_turns")
            if cost is not None:
                print(f"[{turns} turns, ${cost:.4f}]", file=sys.stderr)
            if result_text:
                print(result_text)
    elif msg_type == "rate_limit_event":
        info = msg.get("rate_limit_info", {})
        status = info.get("status", "unknown")
        if status != "allowed":
            print(f"[Rate limit: {status}]", file=sys.stderr)
    elif msg_type == "error":
        print(f"[ERROR] {msg.get('error', 'Unknown')}", file=sys.stderr)


def _format_age(started_at: float) -> str:
    """Format a timestamp as a human-readable age string."""
    if not started_at:
        return "?"
    delta = time.time() - started_at
    if delta < 60:
        return f"{int(delta)}s"
    elif delta < 3600:
        return f"{int(delta / 60)}m"
    elif delta < 86400:
        return f"{int(delta / 3600)}h"
    else:
        return f"{int(delta / 86400)}d"


def _format_cost(cost_usd) -> str:
    """Format cost as $X.XX or - if None."""
    if cost_usd is None:
        return "-"
    return f"${cost_usd:.2f}"


def _print_sessions_table(sessions: list):
    """Print sessions as a formatted table."""
    if not sessions:
        print("No sessions found.")
        return

    print(f"  {'ID':<9}{'TITLE':<40}{'SOURCE':<8}{'AGE':<7}{'MSGS':>5}  {'COST':>6}")
    for s in sessions:
        sid = s["id"][:4] + ".."
        title = (s.get("title") or "(untitled)")[:39]
        source = (s.get("source") or "?")[:7]
        age = _format_age(s.get("started_at"))
        msgs = s.get("message_count", 0)
        cost = _format_cost(s.get("cost_usd"))
        print(f"  {sid:<9}{title:<40}{source:<8}{age:<7}{msgs:>5}  {cost:>6}")


def _print_search_results(results: list):
    """Print search results."""
    if not results:
        print("No results found.")
        return

    for r in results:
        sid = r["session_id"][:8]
        role = r.get("role", "?")
        source = r.get("source", "?")
        snippet = r.get("snippet", r.get("content", ""))[:80]
        title = r.get("title") or "(untitled)"
        age = _format_age(r.get("started_at"))
        print(f"  [{sid}] {title} ({source}, {age})")
        print(f"    {role}: {snippet}")
        print()


async def _run_oneshot(prompt: str, cwd: str, config, resume_session_id=None):
    """Run a single prompt and exit."""
    agent = AionAgent(config)

    async for msg in agent.run(prompt, source="cli", cwd=cwd,
                               resume_session_id=resume_session_id):
        _print_message(msg)


async def _run_interactive(cwd: str, config, resume_session_id=None):
    """Interactive REPL."""
    agent = AionAgent(config)

    # Track the Aion session ID for carry-across-turns
    current_resume_id = resume_session_id

    print("Aion — Anthropic-native AI agent")
    print(f"Model: {config.model}")
    print(f"Memory: {agent.memory._char_count('memory')}/{config.memory.char_limit} chars")
    if current_resume_id:
        print(f"Resuming session: {current_resume_id[:8]}...")
    print("Type /quit to exit, /help for commands\n")

    while True:
        try:
            prompt = input("→ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not prompt:
            continue
        if prompt.lower() in ("/quit", "/exit", "/q"):
            print("Bye!")
            break

        # --- REPL commands ---
        if prompt.lower() == "/help":
            print("  /sessions        — List recent sessions")
            print("  /resume ID       — Resume a session by ID prefix")
            print("  /search QUERY    — Search past sessions")
            print("  /memory          — Show current memory snapshot")
            print("  /quit            — Exit")
            print()
            continue

        if prompt.lower() == "/sessions":
            sessions = agent.recent_sessions(20)
            _print_sessions_table(sessions)
            print()
            continue

        if prompt.lower().startswith("/resume"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                print("Usage: /resume SESSION_ID")
                print()
                continue
            prefix = parts[1].strip()
            resolved = agent.sessions.resolve_session_id(prefix)
            if not resolved:
                print(f"No unique session matching '{prefix}'")
                print()
                continue
            current_resume_id = resolved
            session = agent.sessions.get_session(resolved)
            title = (session.get("title") or "(untitled)") if session else "?"
            print(f"Resumed session: {resolved[:8]}.. — {title}")
            print()
            continue

        if prompt.lower().startswith("/search"):
            parts = prompt.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                print("Usage: /search QUERY")
                print()
                continue
            query = parts[1].strip()
            results = agent.sessions.search(query, limit=10)
            _print_search_results(results)
            continue

        if prompt.lower() == "/memory":
            snap = agent.memory.snapshot
            if snap.get("memory"):
                print("── MEMORY.md ──")
                print(snap["memory"])
            if snap.get("user"):
                print("── USER.md ──")
                print(snap["user"])
            if not snap.get("memory") and not snap.get("user"):
                print("(no memory entries)")
            print()
            continue

        # --- Normal prompt ---
        async for msg in agent.run(prompt, source="cli", cwd=cwd,
                                   resume_session_id=current_resume_id):
            _print_message(msg)

        # Carry session forward: use the most recent Aion session ID
        # so the next turn resumes the same CC session
        recent = agent.sessions.recent_sessions(1)
        if recent:
            current_resume_id = recent[0]["id"]

        print()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (exposed for testing)."""
    from . import __version__
    parser = argparse.ArgumentParser(description="Aion — Anthropic-native AI agent")
    parser.add_argument("-v", "--version", action="version", version=f"aion {__version__}")
    parser.add_argument("prompt", nargs="?", help="One-shot prompt (omit for interactive mode)")
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--gateway", help="Start gateway (telegram, discord, slack)")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--resume", metavar="SESSION_ID",
                        help="Resume a previous session (supports prefix matching)")
    parser.add_argument("--continue", dest="continue_session", action="store_true",
                        help="Resume the most recent session")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--sessions", action="store_true",
                        help="List recent sessions and exit")
    parser.add_argument("--search", metavar="QUERY",
                        help="Search sessions and exit")
    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    cwd = str(Path(args.cwd).resolve())
    config = load_config(Path(args.config) if args.config else None)

    # --model override
    if args.model:
        config.model = args.model

    # Configure structured logging early
    if args.gateway:
        from .gateway.runner import start_gateway
        configure_logging(json_output=True, level="INFO")
        asyncio.run(start_gateway(config))
        return

    configure_logging(json_output=False, level="WARNING")

    # --sessions: list and exit
    if args.sessions:
        db = SessionDB(config.aion_home / "state.db")
        db.connect()
        sessions = db.recent_sessions(20)
        _print_sessions_table(sessions)
        db.close()
        return

    # --search: search and exit
    if args.search:
        db = SessionDB(config.aion_home / "state.db")
        db.connect()
        results = db.search(args.search, limit=10)
        _print_search_results(results)
        db.close()
        return

    # Resolve --resume / --continue
    resume_session_id = None
    if args.resume:
        db = SessionDB(config.aion_home / "state.db")
        db.connect()
        resolved = db.resolve_session_id(args.resume)
        db.close()
        if not resolved:
            print(f"Error: No unique session matching '{args.resume}'", file=sys.stderr)
            sys.exit(1)
        resume_session_id = resolved
    elif args.continue_session:
        db = SessionDB(config.aion_home / "state.db")
        db.connect()
        recent = db.recent_sessions(1)
        db.close()
        if not recent:
            print("Error: No sessions to continue", file=sys.stderr)
            sys.exit(1)
        resume_session_id = recent[0]["id"]

    # If stdin is piped (not a TTY) and no prompt arg, read from stdin
    if not args.prompt and not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            asyncio.run(_run_oneshot(piped, cwd, config, resume_session_id))
            return

    if args.prompt:
        asyncio.run(_run_oneshot(args.prompt, cwd, config, resume_session_id))
    else:
        asyncio.run(_run_interactive(cwd, config, resume_session_id))


if __name__ == "__main__":
    main()
