# CLI Hardening — Make Aion Usable

## Goal
Make the CLI actually usable for real work — session resume, model selection, session listing.

## Current State
Read `src/aion/cli.py` (100 LOC) — has basic one-shot and interactive mode.
Read `src/aion/agent.py` (174 LOC) — has `resume_session_id` param already.
Read `src/aion/memory/sessions.py` — has `recent_sessions()`, `get_cc_session_id()`, `resolve_session_id()`.

## Boundaries
- Do NOT modify sessions.py, store.py, llm.py, or search.py
- Do NOT add new dependencies
- Keep the CLI simple — argparse, no rich/click

## Tasks (1 commit)

Add these CLI flags:
- `--resume SESSION_ID` — resume a previous session (passes to agent.run's resume_session_id). Supports prefix matching via `db.resolve_session_id()`.
- `--continue` — resume the most recent session (get from `db.recent_sessions(1)`)
- `--model MODEL` — override model (passes to agent config)
- `--sessions` — list recent sessions and exit (formatted table: id prefix, title, source, age, messages, cost)
- `--search QUERY` — search sessions and exit (use `db.search()`, print formatted results)

For interactive mode:
- Add `/sessions` command (same as --sessions)
- Add `/resume ID` command
- Add `/search QUERY` command  
- Add `/memory` command — show current memory snapshot
- Session resume should carry across the REPL — after one prompt, the next should continue the same CC session

Format `--sessions` output as:

```
  ID       TITLE                  SOURCE  AGE    MSGS  COST
  a3f2..   fix auth module        cli     2h     12    $0.03
  b7e1..   add telegram adapter   tg      1d     45    $0.12
```

Test: `tests/test_cli.py` — test argument parsing (--resume, --continue, --model, --sessions), test session listing format.

Run `uv run python -m pytest tests/ -v` after changes to verify all tests pass.
