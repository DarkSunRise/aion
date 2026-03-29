# Aion Integration Libraries Research

## Date: 2026-03-29
## Context

Aion (Python, wraps claude-agent-sdk) needs integration libraries for messaging gateways,
MCP, structured output, and general agent patterns. The gateway module exists but is empty
(`src/aion/gateway/` scaffolded with empty `__init__.py` files).

Current deps: `claude-agent-sdk>=0.1.52`, `anthropic>=0.86.0`, `aiohttp>=3.13.4`,
`python-telegram-bot>=22.7`, `pyyaml>=6.0`

---

## Sibling Project Dependencies (for pattern alignment)

### claude-orchestra (TS)
- `@anthropic-ai/claude-agent-sdk ^0.2.81`
- `@modelcontextprotocol/sdk ^1.27.1`
- `zod ^4.3.6` (schema validation — Python equiv: pydantic)
- `better-sqlite3 ^12.8.0`
- `simple-git ^3.33.0`

### Ouroboros/Oro (TS, under ~/oro and ~/dev/awo/packages/oro)
- `@anthropic-ai/claude-agent-sdk ^0.2.86`
- `@mastra/core ^1.17.0` + `@mastra/server ^1.17.0` (agent framework)
- `@modelcontextprotocol/sdk ^1.28.0`
- `bullmq ^5.71.1` (job queue)
- `hono ^4.12.9` (HTTP framework)
- `ioredis ^5.10.1`
- `drizzle-orm ^0.45.2`
- `dockerode ^4.0.10`
- `croner ^10.0.1` (cron)
- `zod ^4.3.6`

Key takeaway: sibling projects use MCP SDK, SQLite, zod/schema validation consistently.
Oro adds job queues (bullmq) and a web framework (hono).

---

## 1. Messaging Platform Libraries

### Telegram

| Library | Stars | Async | Webhook | Typing | Notes |
|---------|-------|-------|---------|--------|-------|
| python-telegram-bot | ~28k | Yes (v20+) | Yes | Good | Already in deps. Mature, large community. Handler-based architecture. |
| aiogram | ~5k | Native async | Yes | Excellent | Built async-first with FSM, middleware, filters. Modern design. Smaller community. |

**Verdict: USE python-telegram-bot** — already a dependency, massive community, fully async
since v20. No reason to switch to aiogram unless you need its FSM/middleware patterns
(which Aion doesn't — the SDK is the brain). Stick with what you have.

### Discord

| Library | Stars | Async | Status | Notes |
|---------|-------|-------|--------|-------|
| discord.py | ~15k | Yes | Active (Rapptz returned) | De facto standard. Cog system for modular bots. |
| nextcord | ~2k | Yes | Community fork | Fork from when discord.py was abandoned. Less reason to use now. |
| disnake | ~1.5k | Yes | Community fork | Another fork. Slash commands focus. |

**Verdict: USE discord.py** — canonical choice, actively maintained again. Nextcord/disnake
were created during the abandonment period; discord.py is back and dominant.

### Slack

| Library | Stars | Async | Notes |
|---------|-------|-------|-------|
| slack-bolt | ~1.2k | Yes (async handlers) | Official Slack SDK. Socket Mode + HTTP. Clean middleware pattern. |
| slack-sdk | ~4k | Yes | Lower-level, slack-bolt wraps it. |

**Verdict: USE slack-bolt** — it's the official framework, clean API, async support.
No real alternatives worth considering.

### Matrix

| Library | Stars | Async | Notes |
|---------|-------|-------|-------|
| matrix-nio | ~500 | Yes (native) | E2EE support, well-maintained. The only serious Python Matrix lib. |

**Verdict: EVALUATE** — only needed if Matrix support is requested. It's the only
real option, well-built, async-native. Low priority unless users demand it.

### Signal

No good Python library exists. Best approach: **signal-cli-rest-api** (Docker container)
+ HTTP calls via aiohttp.

**Verdict: SKIP native lib, USE signal-cli-rest-api** when Signal support needed.

### Unified Multi-Platform?

No good unified Python messaging library exists. The TS world has grammY (Telegram-specific)
and Botpress/Rasa (too heavy, their own NLU). The right pattern for Aion is what's
already scaffolded: a gateway adapter pattern where each platform gets a thin adapter
that normalizes messages to a common interface. This is the correct approach.

**Verdict: BUILD adapter pattern** (already scaffolded). No library to adopt here.

---

## 2. Agent Framework Patterns

### Full Frameworks (patterns to steal, not adopt)

| Library | Stars | Verdict | Steal What |
|---------|-------|---------|------------|
| LangChain | ~100k | SKIP | Too heavy, wrong abstraction layer for SDK wrapper. |
| LangGraph | ~10k | EVALUATE patterns | State machine for multi-step workflows. Graph-based agent control flow is interesting if Aion grows complex orchestration. |
| CrewAI | ~25k | SKIP | Multi-agent focus, not relevant for single-agent SDK wrapper. |
| AutoGen | ~40k | SKIP | Multi-agent, conversation patterns. Overkill. |
| Mastra | (TS) | Note: Oro uses it | Agent framework with workflows, tools, memory. Python port doesn't exist but patterns are worth studying. |

### Lightweight / Useful Components

| Library | Stars | Verdict | Why |
|---------|-------|---------|-----|
| Pydantic (v2) | ~22k | **USE** | Already implicit via anthropic SDK. Use for config, tool schemas, structured output validation. Not a new dep — anthropic already depends on it. |
| Pydantic AI | ~15k | SKIP | Full agent framework built on Pydantic. Overlaps with claude-agent-sdk. |
| Instructor | ~10k | SKIP | Structured extraction from LLMs. The SDK already has `output_format={type: "json_schema", schema: {...}}` which does this natively. Instructor would be redundant. |
| Mirascope | ~2k | SKIP | Lightweight LLM abstraction. Aion already has the SDK. |

### Patterns Worth Stealing

1. **From LangGraph**: State machine pattern for complex multi-turn conversations
   where Aion needs to track workflow state across messages.
2. **From Mastra (Oro)**: Workflow + tool registration patterns. Oro uses @mastra/core
   for structured agent workflows.
3. **From Instructor**: The pattern of defining Pydantic models as output schemas
   and validating responses. Easy to implement directly with SDK's output_format.

---

## 3. claude-agent-sdk Ecosystem

### Python SDK
- `claude-agent-sdk` on PyPI — Aion already uses it.
- `anthropic` SDK — also already a dep, provides the lower-level API.
- No other significant Python packages wrapping claude-agent-sdk found on PyPI.

### TypeScript Ecosystem (from sibling projects)
- `@anthropic-ai/claude-agent-sdk` — same SDK, TS version (claude-orchestra, Oro use it)
- `@anthropic-ai/sdk` — lower-level Anthropic SDK (Oro uses both)
- `@modelcontextprotocol/sdk` — MCP SDK (both use it)

### Structured Output Pattern
The SDK supports `output_format={"type": "json_schema", "schema": {...}}` natively.
Combined with Pydantic model → JSON schema conversion (`Model.model_json_schema()`),
this gives you Instructor-like structured output for free:

```python
from pydantic import BaseModel

class TaskPlan(BaseModel):
    steps: list[str]
    priority: str

schema = TaskPlan.model_json_schema()
# Pass to SDK: output_format={"type": "json_schema", "schema": schema}
# Parse response: TaskPlan.model_validate_json(response_text)
```

**Verdict: USE Pydantic for schema definition + SDK's native output_format.**
No need for Instructor or Pydantic AI.

---

## 4. MCP Libraries

| Library | Verdict | Why |
|---------|---------|-----|
| `mcp` (Python SDK) | **USE** | Official MCP Python SDK from Anthropic/modelcontextprotocol. Aligns with TS SDK used by claude-orchestra and Oro. Essential for tool interop. |
| FastMCP | **EVALUATE** | Simplified MCP server creation (decorator-based). Good for quickly exposing Aion's tools as MCP servers. May be useful if Aion needs to serve tools to other agents. |

### MCP Tool Ecosystem
Instead of building custom tools, leverage existing MCP servers:
- **filesystem** — file operations
- **brave-search** — web search
- **sqlite** — database access
- **github** — GitHub operations
- **memory** — persistent memory (though Aion has its own)

**Verdict: USE `mcp` Python SDK** — aligns with sibling projects. Add as a core
dependency. FastMCP is nice for creating MCP servers but not urgent.

---

## 5. Infrastructure Libraries (Python equivalents of Oro's TS deps)

| Oro Uses (TS) | Python Equivalent | Verdict | Notes |
|---------------|-------------------|---------|-------|
| better-sqlite3 | `sqlite3` (stdlib) or `aiosqlite` | **USE aiosqlite** | Aion already uses SQLite via sessions. aiosqlite adds async support. |
| zod | pydantic | **USE** (implicit dep) | Already available via anthropic SDK dependency. |
| bullmq | `celery`, `arq`, `rq` | SKIP for now | Job queues not needed until Aion handles concurrent requests at scale. |
| hono | `aiohttp` or `fastapi` | **USE aiohttp** (already a dep) | For webhook endpoints. FastAPI is heavier but has better OpenAPI docs. |
| ioredis | `redis`/`aioredis` | SKIP for now | Not needed until caching/pub-sub required. |
| drizzle-orm | `sqlalchemy`, `tortoise-orm` | SKIP | SQLite via raw queries or aiosqlite is fine for Aion's needs. |
| dockerode | `docker` (docker-py) | SKIP | Not relevant for Aion. |
| croner | `apscheduler` | EVALUATE | Only if Aion needs built-in scheduling. |
| simple-git | `gitpython` | EVALUATE | Only if Aion needs git operations. |
| pino | `structlog` | EVALUATE | Structured logging. Nice to have, not urgent. |

---

## 6. Summary: Recommended Dependency Changes

### ADD to core dependencies:
| Package | Why | Priority |
|---------|-----|----------|
| `mcp` | MCP SDK, aligns with sibling projects | HIGH |
| `pydantic>=2.0` | Schema validation, structured output, config | HIGH (may already be transitive) |
| `aiosqlite` | Async SQLite for gateway/session operations | MEDIUM |

### KEEP as-is:
| Package | Status |
|---------|--------|
| `python-telegram-bot>=22.7` | Good choice, keep |
| `aiohttp>=3.13.4` | Good choice for HTTP/webhooks |
| `pyyaml>=6.0` | Fine for config |

### ADD as optional dependencies (extras):
```toml
[project.optional-dependencies]
discord = ["discord.py>=2.4"]
slack = ["slack-bolt>=1.20"]
matrix = ["matrix-nio>=0.24"]
all-gateways = ["discord.py>=2.4", "slack-bolt>=1.20", "matrix-nio>=0.24"]
```

### SKIP entirely:
- LangChain, CrewAI, AutoGen, Pydantic AI, Instructor, Mirascope
- Any ORM (raw SQLite/aiosqlite is fine)
- Redis, job queues (premature for current stage)
- Any unified bot framework

---

## 7. Architecture Recommendation

```
aion/
  gateway/
    base.py          # Abstract GatewayAdapter with normalize_message/send_response
    adapters/
      telegram.py    # python-telegram-bot adapter
      discord.py     # discord.py adapter (optional dep)
      slack.py       # slack-bolt adapter (optional dep)
      cli.py         # Terminal/stdin adapter (no external dep)
  tools/
    mcp_bridge.py    # MCP client for connecting to external tool servers
  structured/
    schemas.py       # Pydantic models for structured outputs
    helpers.py       # output_format builder from Pydantic models
```

The gateway adapter pattern (already scaffolded) is correct. Each adapter should:
1. Accept platform-specific messages
2. Normalize to `GatewayMessage(text, sender, platform, metadata)`
3. Pass to `AionAgent.run()`
4. Stream responses back through platform-specific send methods

This matches what Hermes does but in Python, and is the right architecture for Aion.
