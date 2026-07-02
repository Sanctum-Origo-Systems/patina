# Phase 6 — MCP Server

**Goal:** Conversational interface via MCP (Model Context Protocol). The agent talks to the app through tools.
After this phase: the app can be used as an MCP server from Claude Code, Cline, or any MCP-compatible host.

**Key principle:** MCP tools are thin wrappers around existing modules from Phase 1-5. They call the same functions the CLI calls — no business logic lives in the MCP layer. Domain modules are the brain; MCP tools and CLI commands are different interfaces to the same brain.

```
User asks "catch me up" via LLM host
    → MCP tool: tools_catch_up.catch_up()
        → Module: priority.catch_up.catch_up() (same function CLI uses)
            → Returns structured data
        → MCP tool formats as markdown string
    → LLM host displays to user
```

**Depends on:** Phase 1-5 (all features exposed as tools)

---

## New Files

```
src/patina/
├── mcp/
│ ├── __init__.py
│ ├── server.py # Server setup + tool registration only
│ ├── tools_catch_up.py # catch_up, priorities, dismiss, acknowledge
│ ├── tools_beliefs.py # beliefs, stale, contradictions, relationships
│ ├── tools_style.py # style_show, draft_reply
│ ├── tools_journal.py # journal_write, journal_search
│ ├── tools_profile.py # profile_read, soul_read
│ ├── tools_objectives.py # objective_list, objective_add, objective_remove
│ └── tools_autonomy.py # autonomy_status, approve, reject

tests/
├── mcp/
│ ├── __init__.py
│ ├── test_server.py # Server starts, tools/list, smoke test
│ ├── test_tools_catch_up.py
│ ├── test_tools_beliefs.py
│ ├── test_tools_style.py
│ ├── test_tools_journal.py
│ └── test_tools_autonomy.py
```

Also: add `mcp` to dependencies in pyproject.toml

---

## Step 1 — MCP Server (`src/patina/mcp/server.py`)

Uses the `mcp` Python SDK (stdio transport).

`server.py` is the registration hub only (~50 lines). It imports tool modules and registers them. Each tool module contains the actual implementations.

Setup:
- Create FastMCP server instance
- Import each `tools_*.py` module and call its `register(server)` function
- Server starts on stdio when invoked

**Pattern for each tool module:**
```python
# tools_catch_up.py
def register(server):
    @server.tool()
    def catch_up(days: int = 3) -> str:
        ...

 @server.tool()
    def priorities(days: int = 7) -> str:
        ...
```

Tools to register (grouped by module):

**Catch-up + Priority:**
- `catch_up(days: int = 3) -> str` — returns formatted catch-up list
- `priorities(days: int = 7) -> str` — returns quadrant-grouped priority list
- `nudges() -> str` — returns items user is neglecting

**Decisions:**
- `dismiss(item_id: str) -> str` — marks observation as dismissed, records decision
- `acknowledge(item_id: str) -> str` — marks as acknowledged
- `done(item_id: str) -> str` — marks as completed

**Beliefs:**
- `beliefs(entity_type: str | None = None) -> str` — list entities with claim count
- `stale(threshold: float = 0.3) -> str` — stale beliefs
- `contradictions() -> str` — tier 1 contradictions
- `relationships(top_n: int = 20) -> str` — relationship rhythms

**Style + Draft:**
- `style_show(entity_name: str) -> str` — show style profile
- `draft_reply(to: str, context: str) -> str` — generate draft using LLM

**Journal:**
- `journal_write(date: str, body: str) -> str` — append journal entry
- `journal_search(query: str, limit: int = 10) -> str` — FTS5 search

**Profile:**
- `profile_read() -> str` — read PROFILE.md content
- `soul_read() -> str` — read SOUL.md content (read-only, no write tool)

**Objectives:**
- `objective_list() -> str` — list active objectives
- `objective_add(label: str, keywords: str = "") -> str` — add objective
- `objective_remove(obj_id: str) -> str` — deactivate objective

**Autonomy:**
- `autonomy_status() -> str` — current level + stats
- `approve(action_id: str) -> str` — approve pending action
- `reject(action_id: str) -> str` — reject pending action

**Guardrails:**
- No `soul_write` or `soul_update` tool exists — agent cannot modify SOUL.md
- `profile_update` only proposes changes (returns diff), does not write

Each tool:
- Calls the underlying function from Phase 1-5
- Returns a formatted string (markdown) for the host LLM to display
- Handles errors gracefully (returns error message string, never raises)

---

## Step 2 — Server Entry Point

Add to `pyproject.toml`:
```toml
[project.scripts]
patina = "patina.cli:app"
patina-mcp = "patina.mcp.server:main"
```

The `main()` function:
- Initializes the store (init_db)
- Starts the MCP server on stdio
- Handles graceful shutdown

---

## Step 3 — MCP Configuration File

Create a template `.mcp.json` or document how to configure:
```json
{
  "mcpServers": {
   "patina-core": {
     "command": "uv",
     "args": ["run", "patina-mcp"],
     "cwd": "/path/to/repo"
    }
  }
}
```

---

## Step 4 — Tests (`tests/mcp/test_server.py`)

Tests:
- Server responds to `tools/list` with all expected tool names
- Each tool can be called with valid args and returns a string (not raises)
- `soul_read` works
- No tool named `soul_write` or `soul_update` exists in tool list
- `catch_up` returns formatted output on seeded data
- `journal_write` + `journal_search` round-trips
- `dismiss` records a decision
- `objective_add` + `objective_list` round-trips

Test approach: call tool functions directly (don't need to spawn server process for unit tests). One smoke test that starts the server and sends tools/list via stdio.

---

## Checklist

- [x] All tests pass
- [x] Server starts on stdio without error
- [x] tools/list returns all expected tools
- [x] Can configure in Claude Code / Cline and use conversationally
- [x] Guardrails enforced (no soul_write)
- [x] Merge to main
- [x] Update Status table in app.md
