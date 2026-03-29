"""Auxiliary LLM calls via claude-agent-sdk.

Thin wrapper around query() for lightweight, single-turn completions
(search summaries, title generation, etc.). No tools, 1 turn, small budget.
"""

import logging
from typing import Optional

from claude_agent_sdk import ClaudeAgentOptions, query

logger = logging.getLogger(__name__)


async def complete(
    prompt: str,
    system: str = "",
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
) -> Optional[str]:
    """Lightweight LLM call — no tools, 1 turn, tiny budget.

    Uses claude-agent-sdk query() so auth flows through the user's
    existing ``claude`` CLI login. No API key needed.

    Returns the result text, or None on error.
    """
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        result_text = None
        async for msg in query(
            prompt=full_prompt,
            options=ClaudeAgentOptions(
                model=model,
                max_turns=1,
                max_budget_usd=0.05,
                permission_mode="bypassPermissions",
                allowed_tools=[],
            ),
        ):
            if hasattr(msg, "result") and msg.result is not None:
                result_text = msg.result
        return result_text
    except Exception:
        logger.warning("Auxiliary LLM call failed", exc_info=True)
        return None
