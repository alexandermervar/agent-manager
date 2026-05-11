# The Council — Design Spec
**Date:** 2026-05-11  
**Repo:** agent-manager  
**Status:** Approved

---

## Overview

The Council is a multi-agent deliberation system built on top of agent-manager. A **Secretary** orchestrator receives requests, convenes the right cabinet members, runs them sequentially (each seeing prior output), and synthesizes a final verdict. All interactions happen through a **web UI**; the same pipeline is also accessible via a `council` CLI command.

---

## Core Concepts

| Term | Meaning |
|---|---|
| **Secretary** | The orchestrator. Briefs, selects agents, synthesizes. Never exposed to the user as a raw agent. |
| **Council member** | Any agent YAML in `agents/`. The Secretary picks from the full roster dynamically. |
| **Session** | One full interaction: brief → select → deliberate → synthesize. Persisted to DB. |
| **Silent mode** | Toggle that skips individual agent responses and returns only the synthesis. |

---

## Architecture

```
Browser (Web UI)
    │  SSE stream
    ▼
FastAPI app  (agent_manager/web/)
    │
    ├── POST /sessions          → start a new session (brief stage)
    ├── POST /sessions/{id}/send → continue brief or trigger council run
    ├── GET  /sessions/{id}/stream → SSE: stage-by-stage events
    ├── GET  /sessions          → list all past sessions
    ├── GET  /sessions/{id}     → full session detail
    ├── GET  /agents            → list all agents
    ├── POST /agents            → create (hire) a new agent
    └── DELETE /agents/{name}   → delete (fire) an agent
    │
    ▼
Secretary pipeline  (agent_manager/secretary.py)
    │
    ├── BriefStage   — back-and-forth with user until task is clear
    ├── SelectStage  — LLM picks council members + explains why
    ├── CouncilStage — runs agents sequentially; each sees prior output
    └── SynthesisStage — Secretary delivers final verdict
    │
    ▼
Existing: executor.py / store.py / agent_loader.py
```

---

## Data Model — New Tables

### `sessions`
```sql
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    title        TEXT,                  -- auto-generated from first message
    status       TEXT NOT NULL,         -- briefing | selecting | deliberating | complete
    silent_mode  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    completed_at TEXT
);
```

### `session_messages`
```sql
CREATE TABLE session_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,   -- user | secretary | agent | system
    agent_name  TEXT,            -- set when role=agent
    stage       TEXT NOT NULL,   -- brief | select | deliberate | synthesis
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    seq         INTEGER NOT NULL -- ordering within session
);
```

Existing `runs` table is reused for individual agent executions. A `session_id` metadata field on runs links them back.

---

## Secretary Pipeline

### Stage 1 — Brief
- Secretary sends an opening message: *"What's on your mind?"*
- User replies. Secretary evaluates whether it has enough context.
- If not, it asks one follow-up question (max 3 rounds).
- When confident, it emits a `stage_change: selecting` event and proceeds.

### Stage 2 — Select
- Single LLM call. Secretary receives: full agent roster + brief summary.
- Returns structured JSON:
  ```json
  {
    "selected": ["finance", "health", "researcher"],
    "rationale": "This involves budget tradeoffs with health implications..."
  }
  ```
- Rationale is streamed to the UI before the council runs.
- If a needed agent doesn't exist, Secretary creates it (YAML written to `agents/`) and adds it to the selected list.

### Stage 3 — Deliberate
- Agents run **sequentially** (not in parallel), ordered by relevance score from Select.
- Each agent receives: the original brief + all prior agent responses concatenated.
- Each response is streamed to the UI as it arrives.
- In **silent mode**: responses are collected but not streamed to the UI until synthesis.

### Stage 4 — Synthesis
- Secretary receives: brief + all agent responses.
- Returns: final recommendation, key points of agreement/disagreement, suggested next steps.
- Always shown, regardless of silent mode.

---

## Dynamic Agent Management (Hire / Fire)

**Hire:** Secretary can call an internal `create_agent(name, role_description)` function during the Select stage. It generates a system prompt via LLM and writes a YAML to `agents/`. The new agent is immediately available for the current session.

**Fire:** Via the web UI (`DELETE /agents/{name}`) or CLI (`agentmgr agents delete <name>`). Soft-delete: YAML is moved to `agents/_archived/` so runs referencing it don't break.

---

## CLI Command

```bash
agentmgr council "What should I do about my health and budget this month?"

# Options:
agentmgr council "<message>" --silent          # synthesis only
agentmgr council "<message>" --agents finance,health  # force specific agents
agentmgr council "<message>" --no-brief        # skip back-and-forth, run immediately
```

The CLI runs the same Secretary pipeline, prints each stage with Rich panels, and exits when synthesis is complete.

---

## Web UI

**Stack:** FastAPI + Jinja2 templates + vanilla JS. No frontend framework. SSE for streaming. SQLite is the only datastore.

**Pages:**

| Route | Purpose |
|---|---|
| `/` | New session — input box, silent mode toggle |
| `/sessions` | History — list of past sessions, click to re-read |
| `/sessions/{id}` | Session view — full deliberation thread |
| `/agents` | Roster — list, create, delete agents |

**Session view layout:**
- Left sidebar: session history list
- Main area: the deliberation thread, streaming in real time
  - Brief exchange (user/secretary bubbles)
  - "Convening council: finance, health, researcher — [rationale]"
  - Each agent response in a labeled card
  - Secretary synthesis at the bottom, visually distinct

**Silent mode toggle:** top-right of the session view. Persisted per session in the DB.

---

## File Structure (additions)

```
agent-manager/
├── agent_manager/
│   ├── secretary.py          # Secretary pipeline (Brief/Select/Deliberate/Synthesize)
│   ├── web/
│   │   ├── __init__.py
│   │   ├── app.py            # FastAPI app, routes, SSE
│   │   └── templates/
│   │       ├── base.html
│   │       ├── index.html    # new session
│   │       ├── session.html  # deliberation thread
│   │       ├── sessions.html # history
│   │       └── agents.html   # roster management
│   └── ... (existing files unchanged)
├── agents/
│   └── _archived/            # soft-deleted agents
└── docs/
    └── superpowers/specs/
        └── 2026-05-11-council-design.md
```

`setup.py` gets a new entry point: `agentmgr-web` → `agent_manager.web.app:start`.

---

## What Is Not In Scope

- Authentication / multi-user
- Agent-to-agent real-time debate (agents see completed prior output, not live streams)
- Memory/context that persists across sessions (each session is independent)
- Mobile layout (desktop-first)

---

## Success Criteria

1. `agentmgr council "..."` runs a full Secretary pipeline from the terminal.
2. `agentmgr-web` (or `uvicorn`) starts the web server; the UI loads in a browser.
3. A new session streams each stage in real time.
4. Silent mode toggle hides individual agent cards and shows only synthesis.
5. Agents can be hired from the UI and immediately appear in the roster.
6. Fired agents are archived, not deleted; past runs still resolve.
