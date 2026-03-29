"""Strip ANSI escape codes from text.

Claude Code output often contains ANSI color/cursor sequences that
look like garbage on messaging platforms. This module removes them.
"""

import re

# Matches all common ANSI escape sequences:
# - CSI sequences: ESC[ ... final_byte (colors, cursor movement, etc.)
# - OSC sequences: ESC] ... ST (hyperlinks, window titles, etc.)
# - Simple two-char escapes: ESC followed by a single character
_ANSI_RE = re.compile(
    r"\x1b"        # ESC character
    r"(?:"
    r"\[[0-9;?]*[A-Za-z]"   # CSI sequences: ESC[...letter
    r"|"
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences: ESC]...BEL or ESC]...ST
    r"|"
    r"[()][AB012]"           # Character set selection
    r"|"
    r"[A-Z]"                 # Simple two-char sequences (ESC + letter)
    r")"
)


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)
