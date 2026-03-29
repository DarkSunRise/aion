# Aion Self-Dogfood Session

## Goal

You are Aion, working on your own codebase. Your job is to improve yourself
by finding and fixing real issues — bugs, missing edge cases, test gaps,
code quality problems. You are both the developer and the QA.

## Context

- Repo: ~/dev/aion (you're already here)
- Stack: Python 3.11+, uv + hatchling, claude-agent-sdk
- Tests: `uv run python -m pytest tests/ -v --tb=short`
- Your own source: src/aion/
- You ARE the tool you're improving — act accordingly

## Boundaries

- Do NOT refactor for style. Only fix real bugs or add missing functionality.
- Do NOT change architecture decisions (SDK is the brain, raw sqlite3, etc.)
- Do NOT touch docs/ — focus on src/ and tests/
- Do NOT modify test infrastructure or conftest patterns
- Commit after each logical fix with a descriptive message
- Run tests before AND after every change — never leave them broken
- If you break something, revert and try again

## Phase 1: Audit (read only, no changes)

1. Read docs/HANDOVER.md for project context
2. Read src/aion/cli.py — the entry point users interact with
3. Read src/aion/agent.py — the core agent loop
4. Read src/aion/config.py — configuration loading
5. Read src/aion/memory/store.py — memory persistence
6. Read src/aion/memory/sessions.py — session database
7. Read src/aion/llm.py — auxiliary LLM calls
8. Skim tests/ to understand coverage

For each file, note:
- Unhandled edge cases (empty inputs, None values, type mismatches)
- Missing error handling (bare except, swallowed errors, no cleanup)
- Logic bugs (off-by-one, race conditions, state leaks)
- Missing test coverage for important paths
- Defensive coding gaps (what happens if SDK returns unexpected data?)

Write your findings to /tmp/aion-audit.md before proceeding.

## Phase 2: Fix (one at a time)

For each issue found in Phase 1, in priority order:

1. Write or update a test that exposes the bug (red)
2. Fix the bug in source (green)
3. Run full test suite — must pass
4. Commit with message: `fix(module): description of what was wrong`

If a fix is too risky or complex, skip it and note why in the audit file.

## Phase 3: Harden

Look for areas where you can add defensive tests:
- What happens when config.yaml is malformed YAML?
- What happens when state.db is locked by another process?
- What happens when the SDK returns an unknown message type?
- What happens on disk full / permission denied for memory files?
- What happens when session search returns 0 results in various code paths?

Add tests for the most important 3-5 gaps. Don't over-test — focus on
things that would cause silent data loss or crashes.

## Success Criteria

- All tests pass (existing + new)
- Each fix has a clean commit
- No regressions introduced
- Audit file documents what was found, what was fixed, what was skipped
