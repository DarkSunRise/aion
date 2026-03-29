"""
CLI entry point for Aion.

Usage:
    aion "write a haiku"                    # One-shot
    aion                                     # Interactive
    aion --gateway telegram                  # Start gateway
"""

import asyncio
import argparse
import sys
from pathlib import Path

from .config import load_config
from .agent import AionAgent


def _print_message(msg: dict):
    """Print a message dict to stdout."""
    msg_type = msg.get("type", "")

    if msg_type == "assistant" and "content" in msg:
        print(msg["content"])
    elif msg_type == "result":
        if msg.get("is_error"):
            print(f"\n[ERROR] {msg.get('result', 'Unknown error')}", file=sys.stderr)
        else:
            result = msg.get("result", "")
            if result:
                print(result)
            cost = msg.get("cost_usd")
            turns = msg.get("num_turns")
            if cost is not None:
                print(f"\n[{turns} turns, ${cost:.4f}]", file=sys.stderr)
    elif msg_type == "error":
        print(f"[ERROR] {msg.get('error', 'Unknown')}", file=sys.stderr)


async def _run_oneshot(prompt: str, cwd: str):
    """Run a single prompt and exit."""
    config = load_config()
    agent = AionAgent(config)

    async for msg in agent.run(prompt, source="cli", cwd=cwd):
        _print_message(msg)


async def _run_interactive(cwd: str):
    """Interactive REPL."""
    config = load_config()
    agent = AionAgent(config)

    print("Aion — Anthropic-native AI agent")
    print(f"Model: {config.model}")
    print(f"Memory: {agent.memory._char_count('memory')}/{config.memory.char_limit} chars")
    print("Type /quit to exit\n")

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

        async for msg in agent.run(prompt, source="cli", cwd=cwd):
            _print_message(msg)
        print()


def main():
    parser = argparse.ArgumentParser(description="Aion — Anthropic-native AI agent")
    parser.add_argument("prompt", nargs="?", help="One-shot prompt (omit for interactive mode)")
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--gateway", help="Start gateway (telegram, discord, slack)")
    parser.add_argument("--config", help="Path to config.yaml")

    args = parser.parse_args()

    cwd = str(Path(args.cwd).resolve())

    if args.gateway:
        # TODO: Launch gateway
        print(f"Gateway mode: {args.gateway} (not yet implemented)")
        sys.exit(1)

    if args.prompt:
        asyncio.run(_run_oneshot(args.prompt, cwd))
    else:
        asyncio.run(_run_interactive(cwd))


if __name__ == "__main__":
    main()
