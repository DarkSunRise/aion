# Aion Codebase Inventory

**Generated:** 2026-03-29
**Location:** `~/dev/aion`
**Build system:** uv + hatchling
**Python:** >=3.11
**Total source LOC:** 945 (excl. tests, docs, config)

---

## Summary

| Status     | Count | Description                                    |
|------------|-------|------------------------------------------------|
| Complete   | 6     | Fully implemented, functional modules          |
| Scaffold   | 3     | Empty `__init__.py` — package exists, no code  |
| Missing    | 8+    | Referenced in docs/config but not yet created  |

---

## Source Files

### Complete

| Path | LOC | Description | External Deps |
|------|-----|-------------|---------------|
| `src/aion/agent.py` | 174 | Core orchestrator — wraps `claude_agent_sdk.query()`, streams results, injects memory into system prompt, tracks sessions in SQLite, handles resume via CC session IDs | `claude-agent-sdk` (query, ClaudeAgentOptions) |
| `src/aion/cli.py` | 100 | CLI entry point — argparse, one-shot mode, interactive REPL, message printing. Gateway flag parsed but not implemented. | (stdlib only) |
| `src/aion/config.py` | 143 | Config management — YAML loader with `${ENV}` interpolation, dataclasses for AionConfig/MemoryConfig/AuditConfig/AuxiliaryConfig, defaults | `pyyaml` |
| `src/aion/redact.py` | 43 | Secret redaction — regex patterns for Anthropic/OpenAI/GitHub/AWS/Slack/GitLab keys, bearer tokens, passwords. 13 patterns. | (stdlib only) |
| `src/aion/memory/store.py` | 293 | Bounded curated memory — MEMORY.md + USER.md with file locking (fcntl), dedup, char limits, frozen snapshots for prompt cache stability, injection/exfiltration scanning (invisible chars, prompt injection patterns) | (stdlib only) |
| `src/aion/memory/sessions.py` | 192 | SQLite session persistence — FTS5 full-text search, WAL mode, schema versioning, session CRUD, message storage, CC session ID tracking for resume | (stdlib: sqlite3) |

### Scaffold (empty `__init__.py` — package exists, no implementation)

| Path | LOC | Description | What's Expected |
|------|-----|-------------|-----------------|
| `src/aion/__init__.py` | 0 | Package root | Version export, public API re-exports |
| `src/aion/gateway/__init__.py` | 0 | Gateway package | Gateway runner, adapter registry, message routing |
| `src/aion/gateway/adapters/__init__.py` | 0 | Adapters sub-package | Adapter base class, adapter registry |
| `src/aion/tools/__init__.py` | 0 | MCP tools package | Tool registration, MCP server helpers |
| `src/aion/memory/__init__.py` | 0 | Memory package | Re-exports of MemoryStore, SessionDB |

### Missing (referenced in docs/config/code but not yet created)

| Expected Path | Referenced In | Purpose |
|---------------|---------------|---------|
| `src/aion/gateway/adapters/telegram.py` | README, CLAUDE.md, pyproject.toml (`python-telegram-bot` dep) | Telegram bot adapter — receive messages, call agent.run(), send responses |
| `src/aion/gateway/adapters/discord.py` | README, config.yaml example | Discord bot adapter |
| `src/aion/gateway/adapters/slack.py` | README, CLI `--gateway` flag | Slack bot adapter |
| `src/aion/gateway/runner.py` | CLAUDE.md ("Register in gateway runner") | Gateway lifecycle — start/stop adapters, message routing |
| `src/aion/gateway/adapters/base.py` | CLAUDE.md architecture | Base adapter class/protocol |
| `src/aion/tools/*.py` (any tool) | CLAUDE.md ("TTS, image-gen, etc.") | MCP tool servers for capabilities not in CC |
| `tests/test_agent.py` | — | Tests for AionAgent (currently untested) |
| `tests/test_cli.py` | — | Tests for CLI |
| `tests/test_sessions.py` | — | Tests for SessionDB (currently untested) |
| `tests/test_config.py` | — | Tests for config loading |

---

## Test Files

| Path | LOC | Tests | Status |
|------|-----|-------|--------|
| `tests/test_memory.py` | 109 | 8 tests | Complete — covers add/replace/remove, char limits, dedup, injection blocking, snapshot freezing, system prompt block |
| `tests/test_redact.py` | 38 | 7 tests | Complete — covers Anthropic/OpenAI/GitHub/AWS/bearer keys, false positive check, None input |

**Total tests:** ~15-16 (all passing per context)

---

## Project/Config Files

| Path | LOC | Status | Notes |
|------|-----|--------|-------|
| `pyproject.toml` | 39 | Complete | hatchling build, `aion` CLI script entry point, deps + dev deps |
| `README.md` | 94 | Complete | Architecture diagram, quick start, memory docs, config example |
| `CLAUDE.md` | 55 | Complete | Dev guide, architecture, instructions for adding adapters/tools |
| `uv.lock` | — | Complete | Lock file |
| `.python-version` | — | Complete | Python version pin |

---

## Dependencies

### Runtime (from pyproject.toml)

| Package | Version | Used By | Status |
|---------|---------|---------|--------|
| `claude-agent-sdk` | >=0.1.52 | `agent.py` — query(), ClaudeAgentOptions | **Active** |
| `anthropic` | >=0.86.0 | Transitive (via claude-agent-sdk) | **Active** |
| `aiohttp` | >=3.13.4 | Not yet imported anywhere | **Unused** (for gateway HTTP) |
| `python-telegram-bot` | >=22.7 | Not yet imported anywhere | **Unused** (for telegram adapter) |
| `pyyaml` | >=6.0 | `config.py` | **Active** |

### Optional

| Package | Version | Extra | Status |
|---------|---------|-------|--------|
| `google-genai` | >=1.0 | `[gemini]` | **Unused** (auxiliary provider not implemented) |

### Dev

| Package | Version | Status |
|---------|---------|--------|
| `pytest` | >=8.0 / >=9.0.2 | **Active** |
| `pytest-asyncio` | >=0.23 / >=1.3.0 | **Active** |

---

## Architecture Gaps

1. **Gateway layer is entirely empty** — all 3 packages scaffolded but no code. Telegram adapter is the highest priority (dep already in pyproject.toml).

2. **Tools layer is entirely empty** — no MCP tool servers implemented yet.

3. **No test coverage for agent.py, cli.py, sessions.py, config.py** — only memory/store.py and redact.py have tests.

4. **`__init__.py` files export nothing** — no public API surface defined.

5. **Auxiliary provider support** — config dataclass exists (AuxiliaryConfig for Gemini) but no implementation code to use it.

6. **CLI gateway flag** — parsed by argparse but prints "not yet implemented" and exits.

7. **Two unused runtime deps** — `aiohttp` and `python-telegram-bot` are declared but not imported anywhere yet.

---

## Code Quality Notes

- Memory store has robust file locking (fcntl), atomic writes (tempfile + os.replace), injection scanning
- Sessions use WAL mode, FTS5, schema versioning — production-ready
- Config supports env var interpolation (`${VAR}`) — good for secrets
- Agent properly streams from SDK, handles errors, tracks costs
- Redaction covers 13 secret patterns with compiled regexes
- All existing code is well-documented with docstrings
