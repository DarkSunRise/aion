# claude-orchestra SDK Patterns — Findings for Aion

## Overview

claude-orchestra is a TypeScript orchestration system that uses `@anthropic-ai/claude-agent-sdk`.
The SDK surface used: `query()` (main entry point), `createSdkMcpServer`, `tool`, and `McpServerConfig` type.

All SDK interaction flows through `query()` — there is **no separate lightweight/headless API**.
Every LLM call, whether a full agentic session or a tiny Haiku enrichment, uses the same `query()` function.

---

## 1. query() Call Patterns

### Pattern A: Full Agentic Session (session.ts:690)
The primary workhorse. Used for task execution with full tool access.

```typescript
const q = query({
  prompt,
  options: {
    allowedTools: ['Read', 'Write', 'Edit', 'Glob', 'Grep', 'Agent', 'Bash(git status*)', ...],
    disallowedTools: ['Bash(rm *)'],
    permissionMode: 'acceptEdits',  // or config-driven
    maxTurns: config.session.maxTurnsPerSession,
    maxBudgetUsd: config.costs.maxPerIteration,
    cwd: config.repoRoot,
    systemPrompt: {
      type: 'preset',
      preset: 'claude_code',
      append: systemAppend,  // containment rules, loop prompt, etc.
    },
    settingSources: ['project'],
    model: 'claude-sonnet-4-6',       // optional, from config
    effort: 'high',                    // optional, from config
    resume: previousSessionId,         // optional, for continuation
    abortController: ac,               // optional, for cancellation
    mcpServers: { ... },               // optional MCP server configs
    outputFormat: {                    // optional, for structured output
      type: 'json_schema',
      schema: WORKER_OUTPUT_SCHEMA,
    },
  },
});
```

### Pattern B: Lightweight Review Session (review.ts:551)
Used for code review — restricted tools, focused model.

```typescript
const q = query({
  prompt,
  options: {
    model: 'claude-sonnet-4-6',       // explicitly Sonnet for reviews
    maxTurns: 8,                       // low turn limit
    maxBudgetUsd: 1.00,               // tight budget
    permissionMode: 'dontAsk',        // no user interaction
    disallowedTools: ['Bash', 'Write', 'Edit', 'Agent', 'NotebookEdit'],
    cwd: repoRoot,
    systemPrompt: 'You are a code review agent...',  // plain string (not preset)
    resume: resumeSessionId,           // optional
  },
});
```

### Pattern C: Minimal Enrichment Call (auto-note.ts:194)
**THIS IS THE KEY PATTERN FOR AION** — lightweight auxiliary LLM call using Haiku.

```typescript
const conversation = queryFn({
  prompt,
  options: {
    model: 'claude-haiku-4-5-20251001',  // cheapest model
    permissionMode: 'dontAsk',
    allowedTools: [],                     // NO tools at all
    maxTurns: 1,                          // single turn only
    maxBudgetUsd: 0.01,                   // $0.01 budget cap
    systemPrompt: 'You are a concise technical briefing writer. Output only the briefing.',
  },
});

let resultText = '';
for await (const event of conversation) {
  if (event.type === 'result' && event.subtype === 'success') {
    resultText = event.result || '';
  }
}
```

### Pattern D: Librarian Session (librarian.ts:214)
Documentation-only session with restricted tools.

```typescript
const q = query({
  prompt,
  options: {
    allowedTools: ['Read', 'Glob', 'Grep', 'Write', 'Edit'],
    disallowedTools: ['Bash(*)'],
    permissionMode: 'acceptEdits',
    maxTurns: config.librarian.maxTurns,
    maxBudgetUsd: config.librarian.maxBudgetUsd,
    cwd: config.repoRoot,
    systemPrompt: {
      type: 'preset',
      preset: 'claude_code',
      append: 'You are the Librarian...',
    },
    model: librarianModel,
  },
});
```

### Pattern E: Copilot Interactive Session (copilot.ts:252)
Long-running interactive session with high turn limit.

```typescript
const q = query({
  prompt,
  options: {
    allowedTools: [...],
    disallowedTools: [...],
    permissionMode: 'default',         // allows user interaction
    maxTurns: 200,                     // high for interactive use
    maxBudgetUsd: config.costs.maxPerRun,
    cwd: config.repoRoot,
    systemPrompt: {
      type: 'preset',
      preset: 'claude_code',
      append: 'You are running in copilot mode...',
    },
    settingSources: ['project'],
    model: config.session.model,
  },
});
```

---

## 2. query() Return Value — Async Iterable

All `query()` calls return an async iterable that yields messages. The iteration pattern:

```typescript
for await (const message of q) {
  switch (message.type) {
    case 'system':
      // subtype 'init' → session_id, model, tools
      // subtype 'compact_boundary' → compaction event
      break;
    case 'assistant':
      // message.message.content[] → text blocks, tool_use blocks
      break;
    case 'user':
      // tool_result blocks
      break;
    case 'rate_limit_event':
      // rate_limit_info with status, utilization, resetsAt
      break;
    case 'result':
      // Final message. Fields:
      //   session_id, total_cost_usd, num_turns, duration_api_ms,
      //   stop_reason, permission_denials, modelUsage, usage,
      //   structured_output (when outputFormat was used)
      //   subtype: 'success' | 'error_max_turns' | 'error_max_budget_usd' | 'error_max_structured_output_retries'
      //   result: string (final text output)
      break;
  }
}
```

Additional methods on the query object:
- `q.accountInfo()` → Promise with subscription info
- `q.initializationResult()` → Promise with available models

---

## 3. Context Compression (context-compressor.ts)

Orchestra does context compression **WITHOUT calling the LLM**. It's purely algorithmic:

### Extractive Compression
- Splits text into units (paragraphs, bullets, code blocks, headings)
- Scores each unit's relevance to the task using term overlap (Jaccard-like)
- Greedily selects highest-scoring units until token budget is met
- Headings always kept for structure
- Token estimation: `chars / 4` (simple heuristic)

### Structured Compression
- Detects document format from filename (workplan, claude.md, loop-prompt, epic)
- Extracts only relevant sections by heading pattern:
  - claude.md → commands, conventions, key patterns, architecture
  - workplan → adjacent task numbers, relevant terms
  - loop-prompt → rules, pitfalls, important, conventions
  - epic → learnings, decisions, context, summary
- Falls back to extractive if still over budget

### Key Insight for Aion
Orchestra does NOT use LLM-based summarization for context compression.
It uses cheap algorithmic extraction. The only LLM-based "summarization" is the
Haiku enrichment call (Pattern C above) which cross-references handoff notes.

---

## 4. Context Management (context-manager.ts)

### Token Budget System
Default 200k total tokens, allocated by slot:

| Slot         | Ratio |
|-------------|-------|
| systemPrompt | 4%   |
| loopPrompt   | 10%  |
| taskContext   | 40%  |
| historical   | 16%  |
| search       | 10%  |
| epic         | 10%  |
| reserve      | 10%  |

### Budget Allocation Algorithm
1. Group items by slot
2. Sort each slot by relevance score (descending)
3. Greedy pack within each slot's budget
4. Surplus from under-used slots redistributed to dropped items by relevance

### Context Items
Each context item has: id, file, section, content, tokens, slot, relevanceScore.
Built via `buildContextItem()` with automatic token estimation.

---

## 5. Session Management

### Session Resumption
Orchestra supports resuming sessions via `resume: sessionId` in query options.
Used for:
- Fix-up loops: resume after validation failure
- Review fix loops: resume after review failure
- Continuation: when context/budget exhausted, resume with WIP diff

### Session Outcome Detection
Three strategies, in priority order:
1. **Structured output**: SDK's `message.structured_output` (when `outputFormat` used)
2. **Manual JSON parse**: Parse result text as JSON matching WorkerStructuredOutput schema
3. **String signals**: Look for `TASK_COMPLETE:`, `TASK_BLOCKED:`, `TASK_SKIPPED:` in text

### Compaction Tracking
Orchestra listens for `system` messages with `subtype: 'compact_boundary'` to track
when the SDK auto-compacts context. Records trigger type and pre-compaction token count.

### Context Utilization Estimation
When the SDK doesn't provide token counts directly, orchestra estimates from session
file size: `fileSize / 20 bytes per token` (rough upper-bound heuristic).

---

## 6. Session DB (db/sessions.ts)

The sessions DB tracks:
- **daily_costs**: date, total_usd, iteration_count, task_count
- **gate_events**: iteration gates (quality, budget, containment)
- **validations**: command results per iteration
- **error_patterns**: recurring error tracking with resolution
- **context_selections**: which context items were included per iteration
- **context_effectiveness**: correlates context selections with iteration outcomes

Key analytics:
- `getContextEffectiveness()`: ranks context sources by success rate
- `getWastedContext()`: finds frequently-included-but-low-success context
- `getRollingAnalysis()`: cost distributions, task type breakdown, efficiency metrics

---

## 7. Model Routing

### Task-Type Based Routing
Models are resolved per task type with fallback chain:
```
models.worker[complexity] → models[taskType] → models.default → session.model → SDK default
```

Task types: 'default', 'validation', 'librarian', 'review'
Complexity levels: 'simple', 'moderate', 'complex'

### Effort Level
Effort is resolved similarly:
```
models.effort[taskType] → models.effort.default → session.effort
```

---

## 8. Provider Abstraction

Orchestra abstracts providers behind `ModelProvider` interface:
- `ClaudeProvider` wraps `session.runSession()`
- `CodexProvider` wraps OpenAI Codex SDK
- Both produce `ProviderSessionResult` with normalized fields

The abstraction is at the session level — individual query() calls (like the Haiku
enrichment) bypass the provider system and call the SDK directly.

---

## 9. MCP Integration

Orchestra uses `createSdkMcpServer` and `tool` from the SDK to create MCP servers
that provide `read_file` and `search_code` tools to worker sessions. These are
passed via the `mcpServers` option in `query()`.

---

## Key Takeaways for Aion

1. **Auxiliary LLM calls use the same query() function** — just with `allowedTools: []`,
   `maxTurns: 1`, `maxBudgetUsd: 0.01`, and a cheap model (Haiku).

2. **Context compression is algorithmic, not LLM-based** — extractive + structured
   section extraction. No summarization calls.

3. **The only "lightweight LLM" pattern is enrichContextNote()** in auto-note.ts —
   Haiku with no tools, 1 turn, $0.01 budget for cross-referencing handoff notes.

4. **Session resumption is a first-class feature** via `resume: sessionId`.

5. **Structured output uses `outputFormat: { type: 'json_schema', schema }` option**.

6. **systemPrompt can be a string OR a preset object** with `type: 'preset', preset: 'claude_code', append: ...`

7. **Budget/turn limits are enforced at the SDK level** via `maxBudgetUsd` and `maxTurns`.

8. **Compaction is handled by the SDK automatically** — orchestra just listens for
   `compact_boundary` system messages.

9. **For Python claude-agent-sdk (Aion's SDK)**, the equivalent patterns would be:
   - Full session: `query(prompt=..., options={...})` with tools enabled
   - Lightweight call: `query(prompt=..., options={model="haiku", allowed_tools=[], max_turns=1, max_budget_usd=0.01})`
   - The async iteration pattern maps to Python's `async for message in conversation:`
