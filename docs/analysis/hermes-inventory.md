# Hermes Agent — Reusable Component Inventory

> Generated from `~/dev/hermes-agent` (v0.4.0, ~579 Python files)
> Focus: components portable to Aion (claude-agent-sdk wrapper)

---

## 1. Gateway / Adapters

### Core Gateway Infrastructure

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `gateway/platforms/base.py` | 1452 | gateway.config, gateway.session, hermes_cli.config | asyncio, abc | Abstract base adapter with message routing, media handling, typing indicators, allowlists |
| `gateway/config.py` | 829 | hermes_cli.config | dataclasses, enum | Gateway configuration: platform enum, PlatformConfig dataclass, session policies, delivery prefs |
| `gateway/session.py` | 1061 | gateway.config | hashlib, threading, uuid | Session lifecycle: SessionSource enum, session key builder, topic-based session management |
| `gateway/delivery.py` | 346 | hermes_cli.config, gateway.config, gateway.session | dataclasses | Message delivery abstraction: chunking, retry, platform-aware formatting |
| `gateway/hooks.py` | 151 | hermes_cli.config | asyncio, importlib, yaml | Plugin hook system: pre/post message processing, extensible pipeline |
| `gateway/mirror.py` | 132 | hermes_cli.config | json | Cross-platform message mirroring (forward messages between platforms) |
| `gateway/pairing.py` | 284 | hermes_cli.config | secrets | Device pairing: generate/verify pairing codes for mobile-to-agent linking |
| `gateway/status.py` | 391 | hermes_constants | json, sqlite3 | Agent status reporting: uptime, connected platforms, session counts |
| `gateway/sticker_cache.py` | 111 | hermes_cli.config | json | LRU sticker ID cache for Telegram/Discord sticker dedup |
| `gateway/stream_consumer.py` | 202 | — | asyncio, queue | Async stream consumer: bridges sync agent output to async platform sends |
| `gateway/channel_directory.py` | 258 | hermes_cli.config | json | Persistent channel/group directory for cross-platform addressing |
| `gateway/run.py` | 5889 | (many) | (many) | Main gateway runner — NOT portable (orchestration glue) |

### Platform Adapters (13 total)

| File | LOC | External Deps | Description |
|------|-----|---------------|-------------|
| `gateway/platforms/telegram.py` | 1906 | python-telegram-bot | Telegram Bot API adapter with threads, stickers, voice, documents |
| `gateway/platforms/telegram_network.py` | 233 | python-telegram-bot | Telegram network/reconnect layer |
| `gateway/platforms/discord.py` | 2212 | discord.py | Discord adapter: slash commands, voice channels, threads, embeds |
| `gateway/platforms/slack.py` | 883 | slack-bolt, slack-sdk | Slack adapter: bolt events, blocks, threads, file uploads |
| `gateway/platforms/whatsapp.py` | 762 | httpx | WhatsApp Cloud API adapter via Meta Business API |
| `gateway/platforms/signal.py` | 774 | httpx | Signal messenger adapter via signal-cli REST API |
| `gateway/platforms/mattermost.py` | 705 | httpx, websockets | Mattermost adapter with WebSocket events |
| `gateway/platforms/matrix.py` | 905 | matrix-nio | Matrix/Element adapter with E2E encryption support |
| `gateway/platforms/homeassistant.py` | 449 | httpx, websockets | Home Assistant conversation agent adapter |
| `gateway/platforms/email.py` | 548 | imaplib, smtplib | Email adapter: IMAP polling + SMTP sending |
| `gateway/platforms/sms.py` | 276 | httpx | SMS adapter via Twilio/webhook API |
| `gateway/platforms/webhook.py` | 559 | aiohttp | Generic inbound/outbound webhook adapter with HMAC auth |
| `gateway/platforms/api_server.py` | 1287 | aiohttp, sqlite3 | REST/SSE API server adapter with job queue, auth, streaming |
| `gateway/platforms/dingtalk.py` | 340 | httpx | DingTalk (Chinese enterprise messenger) adapter |

### ACP (Agent Communication Protocol) Adapter

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `acp_adapter/server.py` | 492 | acp_adapter.auth/events/tools | acp | ACP-compliant agent server exposing Hermes as an ACP agent |
| `acp_adapter/session.py` | 461 | hermes_constants | dataclasses | ACP session state management with message history |
| `acp_adapter/tools.py` | 215 | — | acp | ACP tool schema translation layer |
| `acp_adapter/events.py` | 171 | acp_adapter.tools | acp | ACP event streaming (SSE) for real-time updates |
| `acp_adapter/auth.py` | 24 | — | — | Provider detection for ACP auth |
| `acp_adapter/permissions.py` | 77 | — | acp | ACP permission negotiation (human-in-the-loop) |
| `acp_adapter/entry.py` | 86 | hermes_constants | asyncio | ACP server entry point / bootstrap |

---

## 2. Memory System

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/memory_tool.py` | 548 | hermes_constants, tools.registry | fcntl, json | Bounded MEMORY.md/USER.md file stores with §-delimited entries, file locking, substring matching |
| `hermes_state.py` | 1274 | hermes_constants | sqlite3, threading | SQLite WAL state store: sessions, FTS5 full-text search, message history, compression chains |
| `tools/session_search_tool.py` | 497 | agent.auxiliary_client, tools.registry | asyncio, concurrent.futures | LLM-powered session search across all stored conversations |
| `honcho_integration/client.py` | 436 | hermes_constants | dataclasses | Honcho external memory client: connection management, caching |
| `honcho_integration/session.py` | 991 | honcho_integration.client | queue, threading | Honcho session bridge: async memory flush, fact extraction, context enrichment |
| `tools/honcho_tools.py` | 264 | tools.registry | json | Honcho tool wrappers for agent-accessible memory operations |
| `tools/checkpoint_manager.py` | 548 | hermes_constants | hashlib, shutil, subprocess | Git-based checkpoint system: snapshot/restore working directory state |

---

## 3. Tools / MCP

### Tool Registry & Infrastructure

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/registry.py` | 247 | — | json, logging | **Singleton tool registry** — zero-dep, schema+handler store, toolset grouping ⭐ HIGHLY PORTABLE |
| `model_tools.py` | 472 | tools.registry, toolsets | json, asyncio | Unified tool interface: resolves toolsets, dispatches calls, formats results |
| `toolsets.py` | 611 | — | — | **Toolset definitions** — named tool groups, composition, resolution ⭐ HIGHLY PORTABLE |
| `toolset_distributions.py` | 364 | — | — | **Per-platform toolset mappings** — which tools are available where ⭐ PORTABLE |
| `tools/approval.py` | 632 | — | logging, re, threading | **Command approval system** — allowlist/blocklist, YOLO mode, risk classification ⭐ PORTABLE |
| `tools/interrupt.py` | 28 | — | threading | **Global interrupt event** — cooperative cancellation flag ⭐ TRIVIALLY PORTABLE |

### MCP (Model Context Protocol)

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/mcp_tool.py` | 1859 | hermes_cli.config, tools.registry | asyncio, mcp | MCP client: server lifecycle, tool discovery, stdio/SSE transports, OAuth |
| `tools/mcp_oauth.py` | 249 | — | httpx | MCP OAuth flow: PKCE, token management, callback server |
| `hermes_cli/mcp_config.py` | 634 | hermes_cli.config | yaml | MCP server configuration: YAML schema, validation, hot-reload |

### Core Tools

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/terminal_tool.py` | 1355 | tools.approval, tools.environments.*, tools.interrupt, tools.registry | subprocess, threading | Terminal execution: multi-backend (local/docker/ssh/modal/singularity/daytona) |
| `tools/file_tools.py` | 520 | tools.file_operations, agent.redact, tools.registry | json, threading | File read/write/search tools with redaction |
| `tools/file_operations.py` | 1164 | — | os, re, difflib | **File operation primitives** — ShellFileOperations, diff, patch apply ⭐ PORTABLE |
| `tools/web_tools.py` | 1742 | agent.auxiliary_client, tools.url_safety, tools.website_policy, tools.registry | httpx, firecrawl | Web search, extract, crawl tools |
| `tools/browser_tool.py` | 1955 | agent.auxiliary_client, tools.browser_providers.*, tools.registry | requests, subprocess | CDP browser automation: navigate, click, screenshot, JS eval |
| `tools/delegate_tool.py` | 791 | tools.registry | concurrent.futures | Sub-agent delegation: spawn parallel child agents for tasks |
| `tools/code_execution_tool.py` | 806 | tools.registry | subprocess, tempfile | Sandboxed code execution (Python, JS, shell) with timeout |
| `tools/send_message_tool.py` | 691 | tools.registry | json, ssl | Cross-platform message sending from agent to any connected platform |
| `tools/todo_tool.py` | 268 | tools.registry | json | In-session task list management |
| `tools/clarify_tool.py` | 141 | tools.registry | json | Ask user for clarification (structured follow-up questions) |
| `tools/homeassistant_tool.py` | 490 | tools.registry | asyncio, httpx | Home Assistant entity control and state queries |
| `tools/cronjob_tools.py` | 458 | cron.jobs, tools.registry | json | Cron job CRUD: create, list, delete, enable/disable scheduled tasks |

### Tool Execution Environments

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/environments/base.py` | 99 | hermes_cli.config | abc, subprocess | **Abstract execution environment** ⭐ PORTABLE |
| `tools/environments/local.py` | 476 | tools.environments.base, tools.environments.persistent_shell | subprocess, glob, signal | Local shell execution with persistent shell support |
| `tools/environments/docker.py` | 494 | — | subprocess, uuid | Docker container execution environment |
| `tools/environments/ssh.py` | 232 | tools.environments.base, tools.environments.persistent_shell, tools.interrupt | subprocess, tempfile | SSH remote execution environment |
| `tools/environments/modal.py` | 259 | hermes_cli.config, tools.environments.base, tools.interrupt | asyncio, json | Modal.com serverless execution environment |
| `tools/environments/singularity.py` | 369 | — | subprocess, tempfile | Apptainer/Singularity container execution |
| `tools/environments/daytona.py` | 250 | tools.environments.base, tools.interrupt | — | Daytona cloud workspace execution |
| `tools/environments/persistent_shell.py` | 277 | tools.interrupt | subprocess, threading | **Persistent shell mixin** — keep shell alive across commands ⭐ PORTABLE |

### Media & AI Tools

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/vision_tools.py` | 548 | agent.auxiliary_client | httpx, base64 | Image analysis via multimodal LLM (describe, OCR, compare) |
| `tools/transcription_tools.py` | 556 | hermes_constants | faster-whisper, subprocess | Audio transcription: Whisper-based STT with chunking |
| `tools/tts_tool.py` | 847 | tools.registry | edge-tts, subprocess | Text-to-speech: Edge TTS + ElevenLabs, voice selection |
| `tools/voice_mode.py` | 792 | tools.registry | sounddevice, wave | Real-time voice mode: mic capture, VAD, streaming STT/TTS |
| `tools/image_generation_tool.py` | 562 | tools.debug_helpers, tools.registry | fal-client | Image generation via fal.ai (Flux, SD) with upscaling |
| `tools/mixture_of_agents_tool.py` | 562 | tools.openrouter_client, agent.auxiliary_client, tools.registry | asyncio | Multi-model reasoning: fan-out to N models, synthesize answers |

### Utility Tools

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/fuzzy_match.py` | 482 | — | re, difflib | **9-strategy fuzzy text matching** — find unique substrings in files ⭐ HIGHLY PORTABLE |
| `tools/patch_parser.py` | 455 | — | re, dataclasses, enum | **V4A patch format parser** — parse/apply multi-file patches ⭐ HIGHLY PORTABLE |
| `tools/ansi_strip.py` | 44 | — | re | **ANSI escape code stripper** ⭐ TRIVIALLY PORTABLE |
| `tools/url_safety.py` | 96 | — | ipaddress, socket, urllib | **URL safety checker** — SSRF prevention, private IP detection ⭐ PORTABLE |
| `tools/website_policy.py` | 283 | hermes_constants | fnmatch, threading | Website access policy: allow/block lists, robots.txt-like rules |
| `tools/debug_helpers.py` | 104 | — | json, uuid | **Debug session logger** — structured debug trace to JSON files ⭐ PORTABLE |
| `tools/env_passthrough.py` | 99 | — | os, pathlib | **Environment variable passthrough** — selective env forwarding ⭐ PORTABLE |
| `tools/process_registry.py` | 889 | tools.environments.local, hermes_cli.config, tools.registry | subprocess, threading | Background process manager: spawn, track, stream output, kill |
| `tools/openrouter_client.py` | 33 | — | os | **OpenRouter async client factory** ⭐ TRIVIALLY PORTABLE |
| `tools/tirith_security.py` | 670 | — | hashlib, subprocess, tarfile | Security scanner: binary integrity, supply chain checks |
| `tools/skills_guard.py` | 1105 | — | re, hashlib, dataclasses | **Skill sandboxing/trust system** — signature verification, capability gating ⭐ PORTABLE |

---

## 4. Skills System

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `tools/skills_tool.py` | 1287 | hermes_constants, hermes_cli.config, tools.registry | yaml | Skill execution engine: load index.md, inject context, manage env vars |
| `tools/skills_hub.py` | 2619 | hermes_constants, tools.skills_guard | httpx, yaml | **Skills marketplace** — install/update/publish skills from GitHub/Hub |
| `tools/skills_sync.py` | 295 | hermes_constants | hashlib, shutil | Skill file synchronization: detect changes, update checksums |
| `tools/skill_manager_tool.py` | 672 | tools.registry | json | Agent-facing skill management: list, enable, disable, view details |
| `agent/skill_utils.py` | 203 | hermes_constants | re, yaml | **Skill metadata helpers** — parse frontmatter, match platforms, extract conditions ⭐ PORTABLE |
| `agent/skill_commands.py` | 282 | — | json, re | CLI skill commands: /skill, /skills, quick-access shortcuts |
| `hermes_cli/skills_config.py` | 181 | hermes_cli.config | yaml | Skill configuration UI: enable/disable, set parameters |
| `hermes_cli/skills_hub.py` | 1181 | hermes_cli.config | httpx, yaml | CLI frontend for skills hub: browse, install, search |
| `skills/` (directory) | ~107 skills | — | — | Skill definitions as index.md + optional scripts/references/templates |

---

## 5. Config System

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `hermes_constants.py` | 50 | — | os, pathlib | **Zero-dep constants** — HERMES_HOME, API URLs, reasoning efforts ⭐ TRIVIALLY PORTABLE |
| `hermes_cli/config.py` | 2038 | — | yaml, os, platform | **Config loader** — YAML config, env expansion, secret management, atomic writes |
| `hermes_time.py` | 120 | hermes_constants | zoneinfo | **Timezone-aware clock** — reads config, falls back to system tz ⭐ PORTABLE |
| `hermes_cli/env_loader.py` | 45 | — | os | .env file loader (simple key=value parsing) |
| `hermes_cli/colors.py` | 22 | — | — | Terminal color constants |

---

## 6. Agent Core (context management, LLM interaction)

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `agent/auxiliary_client.py` | 1761 | hermes_cli.config, hermes_constants | openai | **LLM client wrapper** — multi-provider (OpenAI, Anthropic, OpenRouter), retry, streaming |
| `agent/anthropic_adapter.py` | 1034 | hermes_constants | anthropic | Anthropic-native API adapter (Claude direct, not via OpenAI compat) |
| `agent/model_metadata.py` | 929 | hermes_constants | requests, yaml | **Model registry** — context lengths, pricing, capability flags, provider detection ⭐ PORTABLE |
| `agent/usage_pricing.py` | 656 | agent.model_metadata | dataclasses, decimal | **Usage tracking & cost calculation** — per-token pricing, session totals ⭐ PORTABLE |
| `agent/prompt_builder.py` | 739 | hermes_constants, agent.skill_utils, utils | json, re | System prompt assembly: identity, skills index, context files, injection detection |
| `agent/context_compressor.py` | 676 | agent.auxiliary_client, agent.model_metadata | — | **Context window compression** — structured summarization of middle turns ⭐ PORTABLE |
| `agent/context_references.py` | 492 | agent.model_metadata | asyncio, subprocess | Context reference resolver: @file, @url, @image inline references |
| `agent/prompt_caching.py` | 72 | — | copy | **Prompt cache helper** — mark cache breakpoints in message arrays ⭐ TRIVIALLY PORTABLE |
| `agent/redact.py` | 165 | — | re | **PII/secret redaction** — regex-based sensitive data masking ⭐ PORTABLE |
| `agent/smart_model_routing.py` | 196 | — | os, re | **Model routing logic** — select model based on task complexity ⭐ PORTABLE |
| `agent/title_generator.py` | 125 | agent.auxiliary_client | threading | Auto-generate conversation titles via LLM |
| `agent/trajectory.py` | 56 | — | json | **Trajectory serializer** — dump message history to JSONL ⭐ TRIVIALLY PORTABLE |
| `agent/insights.py` | 792 | agent.usage_pricing | json, collections | Session analytics: token usage, tool call stats, timing |
| `agent/display.py` | 744 | — | json, threading | Terminal display: streaming output, progress indicators, rich formatting |
| `agent/models_dev.py` | 171 | — | — | Development/experimental model definitions |
| `agent/copilot_acp_client.py` | 447 | — | acp | ACP copilot client: delegate to other ACP agents |
| `trajectory_compressor.py` | 1499 | — | json, yaml, asyncio | **Post-hoc trajectory compression** for training data ⭐ PORTABLE |

---

## 7. Utilities

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `utils.py` | 107 | — | json, yaml, tempfile | **Atomic file writes** — JSON and YAML with fsync+rename safety ⭐ HIGHLY PORTABLE |
| `tools/neutts_synth.py` | 104 | — | struct, argparse | Raw audio synthesis helper (WAV header generation) |
| `tools/browser_providers/base.py` | 59 | — | abc | Abstract cloud browser provider interface |
| `tools/browser_providers/browserbase.py` | 206 | tools.browser_providers.base | httpx | Browserbase.com cloud browser provider |
| `tools/browser_providers/browser_use.py` | 107 | tools.browser_providers.base | — | browser-use library provider |

### Cron System

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `cron/scheduler.py` | 574 | hermes_constants | asyncio, fcntl | **Cron scheduler** — file-locked tick(), due-job detection ⭐ PORTABLE |
| `cron/jobs.py` | 733 | hermes_constants | json, yaml | **Cron job CRUD** — create/read/update/delete jobs in YAML store ⭐ PORTABLE |

### Honcho Integration

| File | LOC | Internal Deps | External Deps | Description |
|------|-----|---------------|---------------|-------------|
| `honcho_integration/client.py` | 436 | hermes_constants | dataclasses | Honcho API client factory with connection pooling |
| `honcho_integration/session.py` | 991 | honcho_integration.client | queue, threading | Honcho session bridge: background memory flush, context enrichment |
| `honcho_integration/cli.py` | 780 | honcho_integration.client | — | Honcho CLI management commands |

---

## 8. Portability Summary — Top Extraction Candidates for Aion

### Tier 1: Zero/minimal internal deps, drop-in reusable

| Component | Files | Total LOC | Why |
|-----------|-------|-----------|-----|
| Tool Registry | `tools/registry.py` | 247 | Zero deps, singleton pattern, schema+handler store |
| Toolsets | `toolsets.py`, `toolset_distributions.py` | 975 | Pure data, no imports |
| Fuzzy Match | `tools/fuzzy_match.py` | 482 | Zero deps, 9-strategy matcher |
| Patch Parser | `tools/patch_parser.py` | 455 | Zero deps, V4A format parser |
| File Operations | `tools/file_operations.py` | 1164 | Zero internal deps, ABC-based |
| ANSI Strip | `tools/ansi_strip.py` | 44 | Zero deps |
| URL Safety | `tools/url_safety.py` | 96 | Zero deps, SSRF prevention |
| Interrupt | `tools/interrupt.py` | 28 | Zero deps, threading.Event |
| Approval System | `tools/approval.py` | 632 | Zero internal deps, risk classification |
| Prompt Caching | `agent/prompt_caching.py` | 72 | Zero deps, cache breakpoint helper |
| Trajectory | `agent/trajectory.py` | 56 | Zero deps, JSONL serializer |
| Redact | `agent/redact.py` | 165 | Zero deps, regex PII masking |
| Atomic Writes | `utils.py` | 107 | Zero deps, JSON/YAML atomic file writes |
| Debug Helpers | `tools/debug_helpers.py` | 104 | Zero deps, structured debug logger |
| Env Passthrough | `tools/env_passthrough.py` | 99 | Zero deps, env var forwarding |
| Smart Routing | `agent/smart_model_routing.py` | 196 | Zero deps, model selection logic |
| **Subtotal** | | **4,922** | |

### Tier 2: Light internal deps, extractable with small refactor

| Component | Files | Total LOC | Deps to resolve |
|-----------|-------|-----------|-----------------|
| Memory Tool | `tools/memory_tool.py` | 548 | hermes_constants (trivial), registry |
| State Store (SQLite) | `hermes_state.py` | 1274 | hermes_constants (trivial) |
| Context Compressor | `agent/context_compressor.py` | 676 | auxiliary_client, model_metadata |
| Model Metadata | `agent/model_metadata.py` | 929 | hermes_constants, requests |
| Usage Pricing | `agent/usage_pricing.py` | 656 | model_metadata |
| Skills Guard | `tools/skills_guard.py` | 1105 | None (standalone dataclasses) |
| Execution Envs | `tools/environments/*.py` | ~2,256 | base.py + interrupt |
| Persistent Shell | `tools/environments/persistent_shell.py` | 277 | interrupt |
| Cron System | `cron/scheduler.py`, `cron/jobs.py` | 1307 | hermes_constants |
| Config Loader | `hermes_cli/config.py` | 2038 | yaml |
| Timezone | `hermes_time.py` | 120 | hermes_constants, zoneinfo |
| Website Policy | `tools/website_policy.py` | 283 | hermes_constants |
| Skill Utils | `agent/skill_utils.py` | 203 | hermes_constants |
| **Subtotal** | | **11,672** | |

### Tier 3: Portable with adapter pattern (need interface abstraction)

| Component | Files | Total LOC | Notes |
|-----------|-------|-----------|-------|
| Gateway Base + Config | `gateway/platforms/base.py`, `gateway/config.py`, `gateway/session.py` | 3,342 | Abstract enough, needs config interface swap |
| Platform Adapters (13) | `gateway/platforms/*.py` | ~11,840 | Each self-contained behind base.py interface |
| MCP Client | `tools/mcp_tool.py`, `tools/mcp_oauth.py` | 2,108 | Needs config abstraction |
| LLM Client | `agent/auxiliary_client.py` | 1,761 | Multi-provider, needs config abstraction |
| Anthropic Adapter | `agent/anthropic_adapter.py` | 1,034 | Claude-native, needs config abstraction |
| Skills Hub | `tools/skills_hub.py` | 2,619 | Marketplace, needs path abstraction |
| Process Registry | `tools/process_registry.py` | 889 | Needs env abstraction |
| Browser Tool | `tools/browser_tool.py` | 1,955 | Heavy but self-contained behind providers |
| **Subtotal** | | **25,548** | |

---

## 9. Dependency Graph (simplified)

```
hermes_constants.py (zero deps — foundation)
    ├── hermes_state.py (sqlite3)
    ├── hermes_time.py (zoneinfo)
    ├── hermes_cli/config.py (yaml)
    │   ├── gateway/config.py
    │   │   ├── gateway/platforms/base.py
    │   │   │   └── gateway/platforms/*.py (13 adapters)
    │   │   └── gateway/session.py
    │   └── agent/auxiliary_client.py (openai)
    │       ├── agent/context_compressor.py
    │       ├── agent/title_generator.py
    │       └── tools/web_tools.py (firecrawl)
    ├── tools/registry.py (zero deps — tool foundation)
    │   └── tools/*.py (all tools register here)
    ├── tools/memory_tool.py
    ├── cron/jobs.py + cron/scheduler.py
    └── tools/skills_hub.py

Standalone (no internal deps):
    tools/fuzzy_match.py, tools/patch_parser.py, tools/file_operations.py,
    tools/ansi_strip.py, tools/url_safety.py, tools/approval.py,
    tools/interrupt.py, agent/redact.py, agent/prompt_caching.py,
    agent/trajectory.py, agent/smart_model_routing.py, utils.py,
    toolsets.py, toolset_distributions.py
```

---

## 10. Recommended Extraction Strategy for Aion

1. **Package `aion-tools-core`** (~5K LOC): registry, toolsets, approval, interrupt, fuzzy_match, patch_parser, file_operations, ansi_strip, url_safety, redact, atomic writes, debug_helpers, env_passthrough
2. **Package `aion-memory`** (~2.3K LOC): memory_tool (MEMORY.md/USER.md stores), hermes_state (SQLite FTS5 sessions), checkpoint_manager
3. **Package `aion-gateway`** (~15K LOC): base adapter, config, session, delivery, stream_consumer + all 13 platform adapters
4. **Package `aion-agent-utils`** (~3.5K LOC): model_metadata, usage_pricing, context_compressor, prompt_caching, smart_model_routing, trajectory, prompt_builder
5. **Package `aion-skills`** (~5.5K LOC): skills_tool, skills_hub, skills_guard, skills_sync, skill_utils, skill_manager_tool + skill definition format
6. **Package `aion-mcp`** (~2.7K LOC): mcp_tool, mcp_oauth, mcp_config
