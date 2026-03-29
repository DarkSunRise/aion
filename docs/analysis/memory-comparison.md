# Hermes → Aion Memory System Comparison

## 1. Lines of Code Comparison

| Component | Hermes File | Hermes LOC | Aion File | Aion LOC | Delta |
|-----------|-------------|------------|-----------|----------|-------|
| Memory Store (MEMORY.md/USER.md) | `tools/memory_tool.py` | 548 | `src/aion/memory/store.py` | 293 | +255 |
| State Store (SQLite+FTS5) | `hermes_state.py` | 1,274 | `src/aion/memory/sessions.py` | 192 | +1,082 |
| Session Search (LLM-powered) | `tools/session_search_tool.py` | 497 | — | 0 | +497 |
| Context Compressor | `agent/context_compressor.py` | 676 | — | 0 | +676 |
| Prompt Builder (memory injection) | `agent/prompt_builder.py` | 739 | — | 0 | +739 |
| **TOTAL** | | **3,734** | | **485** | **+3,249** |

Aion has ~13% of Hermes's memory system code. The ported `store.py` is a clean extraction;
`sessions.py` is minimal scaffolding.

---

## 2. Feature Matrix

| Feature | Hermes | Aion | Notes |
|---------|--------|------|-------|
| **Memory Store (MEMORY.md / USER.md)** | | | |
| Bounded file-backed entries | ✅ | ✅ | Both use § delimiter, char limits |
| Configurable char limits per store | ✅ (2200/1375) | ✅ (2200/1375) | Identical defaults |
| Add/Replace/Remove operations | ✅ | ✅ | Same API |
| Substring-match entry identification | ✅ | ✅ | |
| Duplicate detection | ✅ | ✅ | |
| Multi-match disambiguation | ✅ (returns previews) | ✅ (simpler) | Hermes returns 80-char previews of ambiguous matches |
| Identical-duplicate safe handling | ✅ | ❌ | Hermes: if all matches are identical text, operates on first safely |
| Injection/exfil scanning | ✅ (11 patterns + invisible chars) | ✅ (same patterns) | Ported identically |
| Frozen snapshot for system prompt | ✅ | ✅ | Both freeze at load, never mutate mid-session |
| system_prompt_block() helper | ❌ | ✅ | Aion added convenience method |
| File locking (fcntl) | ✅ | ✅ | Both use .lock file pattern |
| Atomic writes (tempfile + os.replace) | ✅ (with fsync) | ✅ (without fsync) | Hermes adds os.fsync() for crash safety |
| Reload-under-lock pattern | ✅ | ✅ | Both re-read from disk before mutating |
| Read action (in tool dispatch) | ✅ | ❌ | Hermes tool dispatch supports "read" implicitly via schema |
| Tool schema (OpenAI function calling) | ✅ (full schema + registry) | ❌ | Hermes has complete MEMORY_SCHEMA dict |
| Tool registry integration | ✅ | ❌ | Hermes registers in tools.registry |
| Configurable memory_dir | ❌ (hardcoded HERMES_HOME) | ✅ (constructor param) | Aion is more flexible |
| **State Store (SQLite + FTS5)** | | | |
| SQLite WAL mode | ✅ | ✅ | |
| Schema versioning + migrations | ✅ (v1→v6, 6 migrations) | ✅ (v1 only) | Hermes has battle-tested migration system |
| FTS5 virtual table | ✅ | ✅ | |
| FTS5 triggers (insert/delete/update) | ✅ | ✅ | |
| FTS5 query sanitization | ✅ (50+ lines) | ❌ | Hermes sanitizes quotes, operators, hyphens, wildcards |
| FTS5 snippet() extraction | ✅ | ❌ | Hermes uses `snippet()` with highlight markers |
| Sessions table: basic fields | ✅ | ✅ | id, source, user_id, model, started_at, ended_at |
| Sessions: parent_session_id (compression chains) | ✅ | ❌ | Critical for compression-triggered session splitting |
| Sessions: model_config (JSON) | ✅ | ❌ | |
| Sessions: system_prompt storage | ✅ | ❌ | |
| Sessions: end_reason | ✅ | ❌ | |
| Sessions: tool_call_count | ✅ | ❌ | |
| Sessions: detailed token tracking | ✅ (input/output/cache_read/cache_write/reasoning) | ✅ (input/output only) | Hermes tracks 5 token types |
| Sessions: cost tracking | ✅ (estimated + actual, status, source, pricing_version) | ✅ (cost_usd only) | Hermes has rich billing metadata |
| Sessions: billing metadata | ✅ (provider, base_url, mode) | ❌ | |
| Sessions: title management | ✅ (set/get/resolve/lineage/sanitize) | ✅ (basic set) | Hermes has title uniqueness, lineage (#2, #3), sanitization |
| Sessions: title sanitization | ✅ (control chars, unicode, length) | ❌ | |
| Sessions: title uniqueness constraint | ✅ (UNIQUE INDEX WHERE NOT NULL) | ❌ | |
| Sessions: title lineage ("session #2") | ✅ | ❌ | |
| Sessions: cc_session_id (resume) | ❌ | ✅ | Aion-specific for CC CLI resume |
| Session reopen (resume) | ✅ | ❌ | |
| Session prefix resolution | ✅ | ❌ | Resolve partial session ID to full |
| Messages: basic fields | ✅ | ✅ | role, content, tool_name, timestamp, token_count |
| Messages: tool_call_id | ✅ | ❌ | Required for tool call/result pairing |
| Messages: tool_calls (JSON) | ✅ | ❌ | Stores full tool call payloads |
| Messages: finish_reason | ✅ | ❌ | |
| Messages: reasoning fields | ✅ (reasoning, reasoning_details, codex_reasoning_items) | ❌ | Critical for multi-turn reasoning continuity |
| Messages: get_messages_as_conversation() | ✅ | ❌ | Restores OpenAI-format conversation with tool_calls, reasoning |
| Write contention handling | ✅ (BEGIN IMMEDIATE + jitter retry, 15 retries) | ❌ | Hermes handles multi-process WAL contention |
| Thread safety (threading.Lock) | ✅ | ❌ | Hermes wraps all ops in threading.Lock |
| WAL checkpoint management | ✅ (periodic PASSIVE + on close) | ❌ | Prevents unbounded WAL growth |
| list_sessions_rich() | ✅ (preview, last_active, correlated subqueries) | ❌ | Single-query rich listing |
| Source filtering / exclusion | ✅ | ❌ | |
| Session export (single + all) | ✅ | ❌ | |
| Session delete / prune | ✅ (by age, by source) | ❌ | |
| clear_messages() | ✅ | ❌ | |
| Search with surrounding context | ✅ (±1 message) | ❌ | |
| **Session Search (LLM-powered)** | | | |
| FTS5 search → LLM summarization | ✅ | ❌ | Entire subsystem missing |
| Parallel async summarization | ✅ | ❌ | |
| Truncation around matches | ✅ (100K char window) | ❌ | |
| Parent session resolution | ✅ | ❌ | Walks compression chains to root |
| Current session exclusion | ✅ | ❌ | |
| Recent sessions mode (no LLM) | ✅ | ❌ | |
| Role filtering | ✅ | ❌ | |
| Hidden source exclusion | ✅ | ❌ | |
| Retry with backoff | ✅ (3 retries) | ❌ | |
| Tool schema + registry | ✅ | ❌ | |
| **Context Compressor** | | | |
| Token threshold detection | ✅ | ❌ | Entire subsystem missing |
| Pre-flight rough estimate | ✅ | ❌ | |
| Tool output pruning (pre-pass) | ✅ | ❌ | Cheap, no LLM call |
| Head/tail protection | ✅ | ❌ | |
| Token-budget tail protection | ✅ | ❌ | Scales with model context window |
| Structured summary template | ✅ | ❌ | Goal/Progress/Decisions/Files/Next Steps |
| Iterative summary updates | ✅ | ❌ | Preserves info across multiple compactions |
| Tool call/result pair sanitization | ✅ | ❌ | Fixes orphaned pairs after compression |
| Boundary alignment (tool groups) | ✅ | ❌ | Never splits tool_call/result groups |
| Summary merge into tail | ✅ | ❌ | Avoids role alternation violations |
| Compression count tracking | ✅ | ❌ | |
| Context-error step-down | ✅ | ❌ | |
| Scaled summary budget | ✅ | ❌ | Proportional to compressed content |
| **Prompt Builder** | | | |
| Memory injection into system prompt | ✅ | ❌ | Entire subsystem missing from Aion |
| Context file scanning (injection defense) | ✅ | ❌ | |
| SOUL.md / HERMES.md / AGENTS.md loading | ✅ | ❌ | |
| .cursorrules / CLAUDE.md support | ✅ | ❌ | |
| Platform hints (telegram, discord, etc.) | ✅ | ❌ | |
| Skills index (2-layer cache) | ✅ | ❌ | |
| Memory/session_search/skills guidance | ✅ | ❌ | |
| YAML frontmatter stripping | ✅ | ❌ | |
| Git root discovery | ✅ | ❌ | |
| Head/tail truncation for large files | ✅ | ❌ | |

---

## 3. Specific Hermes Features Missing from Aion

### 3.1 Critical (Required for Feature Parity)

1. **Write Contention Handling** (`_execute_write` with BEGIN IMMEDIATE + jitter retry)
   - Hermes handles multi-process SQLite contention (gateway + CLI + worktree agents)
   - Without this, concurrent writes cause "database is locked" errors
   - ~50 LOC

2. **Thread Safety** (threading.Lock on all DB operations)
   - Every read and write in hermes_state.py is wrapped in `self._lock`
   - Essential for gateway multi-platform concurrency

3. **Parent Session Chains** (parent_session_id + foreign key)
   - Compression creates new child sessions linked to parents
   - Session search walks chains to find root conversations
   - Without this, compression breaks session continuity

4. **FTS5 Query Sanitization** (`_sanitize_fts5_query`, ~50 LOC)
   - Handles quotes, special chars, boolean operators, hyphens, wildcards
   - Without this, user search queries cause sqlite3.OperationalError

5. **Message Tool Call Fields** (tool_call_id, tool_calls JSON)
   - Required for tool call/result pairing in conversation replay
   - Without these, gateway session restoration is broken

6. **Reasoning Fields** (reasoning, reasoning_details, codex_reasoning_items)
   - Critical for multi-turn reasoning continuity with OpenRouter/OpenAI/Nous
   - Schema v6 migration in Hermes

### 3.2 Important (High Value)

7. **Context Compressor** (entire 676-LOC subsystem)
   - Without compression, long conversations hit context limits and fail
   - Structured summaries preserve work context across compactions
   - Tool pair sanitization prevents API errors after compression

8. **LLM-Powered Session Search** (entire 497-LOC subsystem)
   - Transforms raw FTS5 matches into focused summaries
   - Parallel async summarization with cheap model
   - Current session exclusion, parent resolution, role filtering

9. **Rich Session Listing** (`list_sessions_rich`)
   - Single-query with correlated subqueries for preview + last_active
   - Source exclusion for hiding internal sessions

10. **Schema Migration System** (v1→v6)
    - Hermes has 6 schema versions with ALTER TABLE migrations
    - Battle-tested across production deployments

### 3.3 Nice-to-Have

11. **Title Management** (uniqueness, lineage, sanitization) - ~100 LOC
12. **WAL Checkpoint Management** (periodic + on-close) - ~30 LOC
13. **Session Export/Prune/Delete** - ~70 LOC
14. **Identical-duplicate safe handling** in memory replace/remove
15. **os.fsync() in atomic writes** for crash safety
16. **Prompt Builder** context file loading (SOUL.md, AGENTS.md, etc.)
17. **Session prefix resolution** (partial ID → full ID)

---

## 4. Recommended Port Priority

### Phase 1: State Store Hardening (CRITICAL — do first)
**Target: `src/aion/memory/sessions.py`** — expand from 192 → ~600 LOC

| Priority | Feature | Est. LOC | Reason |
|----------|---------|----------|--------|
| P0 | Thread safety (threading.Lock) | +30 | Gateway concurrency |
| P0 | Write contention handling (_execute_write) | +60 | Multi-process safety |
| P0 | FTS5 query sanitization | +50 | Prevents crashes on user queries |
| P0 | Schema migration framework (v1→vN) | +80 | Future-proofs DB changes |
| P1 | parent_session_id + chain support | +20 | Required before compression |
| P1 | Message tool_call fields (tool_call_id, tool_calls) | +30 | Tool call replay |
| P1 | Reasoning fields (reasoning, reasoning_details) | +30 | Multi-turn reasoning |
| P1 | get_messages_as_conversation() | +40 | Gateway session restore |
| P1 | WAL checkpoint management | +30 | Prevents WAL bloat |
| P2 | Rich session listing (list_sessions_rich) | +50 | Better UX |
| P2 | Title management (uniqueness, lineage) | +80 | Named sessions |
| P2 | Session export/prune/delete | +70 | Maintenance |

### Phase 2: Context Compressor (HIGH — enables long conversations)
**Target: new `src/aion/agent/compressor.py`** — ~500 LOC (simplified from 676)

| Priority | Feature | Est. LOC | Reason |
|----------|---------|----------|--------|
| P0 | Core compress() with head/tail protection | +150 | Core algorithm |
| P0 | Structured summary generation (LLM) | +100 | Preserves context |
| P0 | Tool pair sanitization | +80 | Prevents API errors |
| P1 | Iterative summary updates | +50 | Better multi-compaction |
| P1 | Token-budget tail protection | +50 | Scales with model |
| P1 | Tool output pruning (pre-pass) | +40 | Cheap optimization |
| P2 | Boundary alignment | +30 | Prevents data loss |

### Phase 3: Session Search (MEDIUM — enables cross-session recall)
**Target: new `src/aion/memory/search.py`** — ~350 LOC (simplified from 497)

| Priority | Feature | Est. LOC | Reason |
|----------|---------|----------|--------|
| P0 | FTS5 search + LLM summarization flow | +150 | Core feature |
| P0 | Truncation around matches | +30 | Context window management |
| P1 | Parent session resolution | +40 | Works with compression chains |
| P1 | Current session exclusion | +30 | Avoids self-reference |
| P1 | Recent sessions mode | +50 | Zero-cost browsing |
| P2 | Parallel async summarization | +50 | Performance |

### Phase 4: Memory Store Enhancements (LOW — mostly done)
**Target: `src/aion/memory/store.py`** — minor additions

| Priority | Feature | Est. LOC | Reason |
|----------|---------|----------|--------|
| P2 | Identical-duplicate safe handling | +15 | Edge case robustness |
| P2 | os.fsync() in atomic writes | +2 | Crash safety |
| P3 | Tool schema definition | +40 | If using OpenAI function calling |

### Phase 5: Prompt Builder (LOW — depends on Aion architecture)
**Target: new `src/aion/agent/prompt_builder.py`** — architecture-dependent

This is highly Hermes-specific (SOUL.md, skills, platform hints). Port selectively
based on Aion's prompt assembly needs.

---

## 5. Key Architectural Differences

1. **Hermes hardcodes paths** via `get_hermes_home()` → Aion uses constructor params (better)
2. **Hermes uses a tool registry** pattern → Aion may have different tool dispatch
3. **Hermes state store is a monolith** (1274 LOC) → Aion could split into sessions.py + search.py + migrations.py
4. **Hermes uses `isolation_level=None`** (manual txn management) → Aion uses default SQLite behavior
5. **Hermes has 6 schema versions** with incremental migrations → Aion starts fresh at v1

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| No write contention handling | DB locks under concurrent access | Port _execute_write first |
| No FTS5 sanitization | Crashes on special-char queries | Port before exposing search to users |
| No compression | Context overflow on long conversations | Port compressor before production use |
| No tool_call fields in messages | Broken tool replay in gateway | Add columns before gateway integration |
| No thread safety | Race conditions in gateway | Add threading.Lock wrapper |
