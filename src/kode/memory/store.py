"""
Persistent curated memory — ported from Hermes.

Two bounded file-backed stores:
  - MEMORY.md: agent's personal notes (env facts, project conventions, tool quirks)
  - USER.md: user profile (preferences, communication style, corrections)

Both injected into system prompt as frozen snapshot at session start.
Writes update files immediately but DON'T change the system prompt mid-session
(preserves prompt cache).

Entry delimiter: § (section sign). Entries can be multiline.
Character limits (not tokens) — model-independent.
"""

import fcntl
import json
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENTRY_DELIMITER = "\n§\n"

# ---------------------------------------------------------------------------
# Injection/exfiltration scanning
# ---------------------------------------------------------------------------

_MEMORY_THREAT_PATTERNS = [
    # Prompt injection
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+(restrictions|limits|rules)', "bypass_restrictions"),
    # Exfiltration
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets"),
    # Persistence
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|~/\.ssh', "ssh_access"),
]

_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
}


def scan_memory_content(content: str) -> Optional[str]:
    """Scan memory content for injection/exfil patterns. Returns error string if blocked."""
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: content contains invisible unicode character U+{ord(char):04X} (possible injection)."

    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: content matches threat pattern '{pid}'."

    return None


class MemoryStore:
    """
    Bounded curated memory with file persistence.

    Maintains two parallel states:
      - _snapshot: frozen at load time, used for system prompt injection.
        Never mutated mid-session. Keeps prompt cache stable.
      - memory_entries / user_entries: live state, mutated by tool calls.
    """

    def __init__(self, memory_dir: Path, memory_char_limit: int = 2200, user_char_limit: int = 1375):
        self.memory_dir = memory_dir
        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self._snapshot: Dict[str, str] = {"memory": "", "user": ""}

    def load(self):
        """Load entries from disk, capture frozen snapshot."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_entries = self._read_file(self.memory_dir / "MEMORY.md")
        self.user_entries = self._read_file(self.memory_dir / "USER.md")

        # Deduplicate
        self.memory_entries = list(dict.fromkeys(self.memory_entries))
        self.user_entries = list(dict.fromkeys(self.user_entries))

        self._snapshot = {
            "memory": self._render("memory"),
            "user": self._render("user"),
        }

    @property
    def snapshot(self) -> Dict[str, str]:
        """Frozen snapshot for system prompt injection."""
        return self._snapshot

    def system_prompt_block(self) -> str:
        """Format memory for injection into append_system_prompt."""
        parts = []
        if self._snapshot["memory"]:
            parts.append(self._snapshot["memory"])
        if self._snapshot["user"]:
            parts.append(self._snapshot["user"])
        return "\n\n".join(parts) if parts else ""

    # --- Mutations ---

    def add(self, target: str, content: str) -> Dict[str, Any]:
        """Add a new entry."""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}

        scan_error = scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._lock(target):
            self._reload(target)
            entries = self._entries(target)
            limit = self._limit(target)

            if content in entries:
                return self._ok(target, "Entry already exists.")

            new_total = len(ENTRY_DELIMITER.join(entries + [content]))
            if new_total > limit:
                current = self._char_count(target)
                return {
                    "success": False,
                    "error": f"Memory at {current:,}/{limit:,} chars. Adding ({len(content)} chars) would exceed limit.",
                    "current_entries": entries,
                    "usage": f"{current:,}/{limit:,}",
                }

            entries.append(content)
            self._set_entries(target, entries)
            self._save(target)

        return self._ok(target, "Entry added.")

    def replace(self, target: str, old_text: str, content: str) -> Dict[str, Any]:
        """Replace an entry identified by substring match."""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}

        scan_error = scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._lock(target):
            self._reload(target)
            entries = self._entries(target)

            matches = [i for i, e in enumerate(entries) if old_text in e]
            if len(matches) == 0:
                return {"success": False, "error": f"No entry contains '{old_text[:50]}'."}
            if len(matches) > 1:
                return {"success": False, "error": f"Multiple entries match '{old_text[:50]}'. Be more specific."}

            entries[matches[0]] = content

            new_total = len(ENTRY_DELIMITER.join(entries))
            limit = self._limit(target)
            if new_total > limit:
                return {"success": False, "error": f"Replacement would exceed {limit:,} char limit."}

            self._set_entries(target, entries)
            self._save(target)

        return self._ok(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> Dict[str, Any]:
        """Remove an entry identified by substring match."""
        with self._lock(target):
            self._reload(target)
            entries = self._entries(target)

            matches = [i for i, e in enumerate(entries) if old_text in e]
            if len(matches) == 0:
                return {"success": False, "error": f"No entry contains '{old_text[:50]}'."}
            if len(matches) > 1:
                return {"success": False, "error": f"Multiple entries match '{old_text[:50]}'. Be more specific."}

            entries.pop(matches[0])
            self._set_entries(target, entries)
            self._save(target)

        return self._ok(target, "Entry removed.")

    # --- Internal helpers ---

    def _entries(self, target: str) -> List[str]:
        return self.user_entries if target == "user" else self.memory_entries

    def _set_entries(self, target: str, entries: List[str]):
        if target == "user":
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _limit(self, target: str) -> int:
        return self.user_char_limit if target == "user" else self.memory_char_limit

    def _char_count(self, target: str) -> int:
        entries = self._entries(target)
        return len(ENTRY_DELIMITER.join(entries)) if entries else 0

    def _path(self, target: str) -> Path:
        return self.memory_dir / ("USER.md" if target == "user" else "MEMORY.md")

    def _render(self, target: str) -> str:
        entries = self._entries(target)
        if not entries:
            return ""
        limit = self._limit(target)
        current = self._char_count(target)
        pct = int(current / limit * 100) if limit else 0
        label = "MEMORY (your personal notes)" if target == "memory" else "USER PROFILE (who the user is)"
        header = f"{'═' * 46}\n{label} [{pct}% — {current:,}/{limit:,} chars]\n{'═' * 46}"
        body = ENTRY_DELIMITER.join(entries)
        return f"{header}\n{body}\n"

    def _ok(self, target: str, message: str) -> Dict[str, Any]:
        entries = self._entries(target)
        current = self._char_count(target)
        limit = self._limit(target)
        pct = int(current / limit * 100) if limit else 0
        return {
            "success": True,
            "target": target,
            "entries": entries,
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
            "message": message,
        }

    @contextmanager
    def _lock(self, target: str):
        lock_path = self._path(target).with_suffix(".md.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(lock_path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    def _reload(self, target: str):
        fresh = self._read_file(self._path(target))
        fresh = list(dict.fromkeys(fresh))
        self._set_entries(target, fresh)

    def _save(self, target: str):
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._write_file(self._path(target), self._entries(target))

    @staticmethod
    def _read_file(path: Path) -> List[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        return [e.strip() for e in text.split("§") if e.strip()]

    @staticmethod
    def _write_file(path: Path, entries: List[str]):
        content = ENTRY_DELIMITER.join(entries)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
