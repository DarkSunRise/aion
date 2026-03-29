"""
Secret redaction for audit safety.

Scans text for common secret patterns and replaces them with [REDACTED].
"""

import re
from typing import List, Tuple

# (pattern, label) — order matters, more specific first
SECRET_PATTERNS: List[Tuple[str, str]] = [
    # API keys
    (r'sk-ant-[a-zA-Z0-9_-]{20,}', '[REDACTED:anthropic_key]'),
    (r'sk-[a-zA-Z0-9_-]{20,}', '[REDACTED:openai_key]'),
    (r'AIza[a-zA-Z0-9_-]{35}', '[REDACTED:google_key]'),
    (r'xoxb-[a-zA-Z0-9-]+', '[REDACTED:slack_token]'),
    (r'xoxp-[a-zA-Z0-9-]+', '[REDACTED:slack_token]'),
    (r'ghp_[a-zA-Z0-9]{36}', '[REDACTED:github_pat]'),
    (r'gho_[a-zA-Z0-9]{36}', '[REDACTED:github_oauth]'),
    (r'glpat-[a-zA-Z0-9_-]{20,}', '[REDACTED:gitlab_pat]'),

    # AWS
    (r'AKIA[A-Z0-9]{16}', '[REDACTED:aws_access_key]'),
    (r'(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*\S+', '[REDACTED:aws_secret]'),

    # Generic patterns
    (r'(?:password|passwd|pwd)\s*[=:]\s*\S+', '[REDACTED:password]'),
    (r'(?:token|secret|api_key|apikey)\s*[=:]\s*["\']?[a-zA-Z0-9_-]{16,}', '[REDACTED:secret]'),

    # Bearer tokens
    (r'Bearer\s+[a-zA-Z0-9_.-]{20,}', '[REDACTED:bearer_token]'),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), r) for p, r in SECRET_PATTERNS]


def redact_secrets(text: str) -> str:
    """Replace detected secrets with redaction labels."""
    if not text or not isinstance(text, str):
        return text
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text
