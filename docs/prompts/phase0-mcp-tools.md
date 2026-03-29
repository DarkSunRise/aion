# Session Prompt: Phase 0.2 — Aion MCP Tools + CC Integration

## Goal

Register Aion's memory, sessions, and search as in-process MCP tools using
the SDK's @tool decorator + create_sdk_mcp_server(). Then wire them into
agent.py so every Aion session (CLI + gateway) gets these tools.

After this, Claude Code can:
- Read/write persistent memory that survives across sessions
- Search past conversations by keyword
- List and browse recent sessions
- Resume past sessions

This turns CC into the orchestration UI with Aion's brain underneath.

## Boundaries

- Do NOT create external MCP server processes — use SDK's in-process @tool
- Do NOT change memory/store.py, memory/sessions.py, or memory/search.py
- Do NOT change the gateway adapters
- Do NOT add new dependencies
- Keep tools simple — thin wrappers around existing Aion methods
- Tests MUST pass: `uv run python -m pytest tests/ -v`
- Commit after each logical unit

## Background

The SDK provides:
```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions

@tool("memory_read", "Read persistent memory", {"target": str})
async def memory_read(args):
    # target: "memory" or "user"
    return {"content": [{"type": "text", "text": result}]}

server = create_sdk_mcp_server("aion", tools=[memory_read, ...])

options = ClaudeAgentOptions(
    mcp_servers={"aion": server},
    allowed_tools=["memory_read", ...],
)
```

Tools run in-process — they have direct access to AionAgent's MemoryStore
and SessionDB instances. No serialization overhead.

## Step-by-Step

### 1. Read existing code first
- Read src/aion/agent.py — understand AionAgent init and run()
- Read src/aion/memory/store.py — MemoryStore API
- Read src/aion/memory/sessions.py — SessionDB API
- Read src/aion/memory/search.py — search_sessions() API

### 2. Create MCP tools module (src/aion/tools/mcp_tools.py)

Define tools that wrap Aion's existing modules. Each tool is a thin async
function decorated with @tool.

**Memory tools:**
```python
@tool("aion_memory_read", 
      "Read Aion's persistent memory (survives across sessions). Target is 'memory' (agent notes) or 'user' (user profile).",
      {"target": str})
async def memory_read(args):
    # Returns the memory content for the given target
    
@tool("aion_memory_add",
      "Add an entry to persistent memory. Use 'memory' for agent notes, 'user' for user profile.",
      {"target": str, "content": str})
async def memory_add(args):
    # Calls store.add(target, content)

@tool("aion_memory_replace",
      "Replace an entry in persistent memory. old_text identifies the entry to replace.",
      {"target": str, "old_text": str, "content": str})
async def memory_replace(args):
    # Calls store.replace(target, old_text, content)

@tool("aion_memory_remove",
      "Remove an entry from persistent memory. old_text identifies the entry to remove.",
      {"target": str, "old_text": str})
async def memory_remove(args):
    # Calls store.remove(target, old_text)
```

**Session tools:**
```python
@tool("aion_sessions_list",
      "List recent Aion sessions with titles, sources, ages, and message counts.",
      {"limit": int})
async def sessions_list(args):
    # Calls db.recent_sessions(limit) or db.list_sessions_rich(limit)

@tool("aion_sessions_search",
      "Search past Aion sessions by keyword. Returns matching messages with context.",
      {"query": str, "limit": int})
async def sessions_search(args):
    # Calls db.search(query, limit)

@tool("aion_session_messages",
      "Get the full conversation from a specific session by ID (or prefix).",
      {"session_id": str})
async def session_messages(args):
    # Resolves prefix, returns formatted conversation
```

**IMPORTANT DESIGN:**
The tools need access to MemoryStore and SessionDB instances. Use a factory
function that closes over the instances:

```python
def create_aion_tools(memory: MemoryStore, sessions: SessionDB) -> list:
    """Create MCP tools bound to Aion's memory and session stores."""
    
    @tool("aion_memory_read", ...)
    async def memory_read(args):
        target = args["target"]
        snapshot = memory.snapshot
        content = snapshot.get(target, "")
        if not content:
            return {"content": [{"type": "text", "text": f"No {target} memory entries."}]}
        return {"content": [{"type": "text", "text": content}]}
    
    # ... more tools ...
    
    return [memory_read, memory_add, memory_replace, memory_remove,
            sessions_list, sessions_search, session_messages]
```

### 3. Create MCP server factory (src/aion/tools/server.py)

```python
from claude_agent_sdk import create_sdk_mcp_server
from .mcp_tools import create_aion_tools

def create_aion_mcp_server(memory, sessions):
    """Create an in-process MCP server with all Aion tools."""
    tools = create_aion_tools(memory, sessions)
    return create_sdk_mcp_server("aion", version="0.2.0", tools=tools)
```

### 4. Wire into agent.py

In AionAgent.__init__ or at the start of run(), create the MCP server
and include it in ClaudeAgentOptions.mcp_servers:

```python
# In AionAgent.__init__:
from .tools.server import create_aion_mcp_server
self._aion_mcp = create_aion_mcp_server(self.memory, self.sessions)

# In run(), when building options:
mcp = {"aion": self._aion_mcp}
if mcp_servers:
    mcp.update(mcp_servers)
options = ClaudeAgentOptions(
    ...
    mcp_servers=mcp,
)
```

Also update continue_session() the same way.

### 5. Update tools/__init__.py

Export the factory functions:
```python
from .server import create_aion_mcp_server
from .mcp_tools import create_aion_tools
```

### 6. Tests

Add tests/test_mcp_tools.py:
- Test each tool function directly (call the async function with args dict)
- Test memory_read returns correct content
- Test memory_add/replace/remove modify the store
- Test sessions_list returns formatted list
- Test sessions_search returns results
- Test session_messages resolves prefixes
- Test create_aion_mcp_server() returns a valid config
- Mock SessionDB for session tests, use real MemoryStore with temp dir

### 7. Update CLAUDE.md

Add a section explaining the MCP tools:
```
## MCP Tools (available in every Aion session)

Aion registers in-process MCP tools that give Claude persistent memory
and session history. These tools are automatically available:

- aion_memory_read — read persistent memory
- aion_memory_add — add to memory
- aion_memory_replace — update memory entry
- aion_memory_remove — delete memory entry
- aion_sessions_list — list recent sessions
- aion_sessions_search — search past sessions
- aion_session_messages — get full conversation from a session
```

## Verification

1. `uv run python -m pytest tests/ -v` — all tests pass
2. `uv run python -m aion.cli "read my memory"` — should use aion_memory_read tool
3. `uv run python -m aion.cli "search sessions for gateway"` — should use aion_sessions_search
4. No unused imports, clean code
5. Each commit is atomic
