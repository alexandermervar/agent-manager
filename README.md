# agent-manager

A Python CLI for defining, running, queuing, and logging multiple AI agents — each with its own system prompt, model, and configuration. Built on the [Anthropic Python SDK](https://github.com/anthropic/anthropic-sdk-python).

---

## What it does

- **The Council web UI** — bring a question to your AI presidential cabinet and get structured, multi-perspective advice
- **Secretary orchestrator** — intelligently selects the right advisors, runs the deliberation, and delivers a synthesized recommendation
- **Define agents in YAML** — give each agent a name, system prompt, model, and tags
- **Run agents immediately** — single or parallel execution from the command line
- **Queue tasks** — submit work to a SQLite-backed queue and drain it in parallel batches
- **Log everything** — every run is persisted with its input, output, token counts, and duration
- **Review history** — inspect past runs by agent, status, or run ID

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/alexandermervar/agent-manager.git
cd agent-manager
pip install -e .

# 2. Set your API key
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-...

# 3. Launch The Council web UI
agentmgr-web
# Open http://localhost:8000 in your browser

# Or use the CLI
agentmgr council "Should I take the new job offer?"
agentmgr agents list
agentmgr run researcher "What is asyncio in Python?"
```

---

## Installation

Requires Python 3.10+.

```bash
pip install -e .
```

Or install dependencies directly:

```bash
pip install -r requirements.txt
```

The CLI is registered as `agentmgr` after install.

---

## Configuration

Create a `.env` file from the example:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `AGENTMGR_DB` | `agent_manager.db` | Path to the SQLite database |
| `AGENTMGR_AGENTS_DIR` | `agents` | Directory containing agent YAML files |

All CLI flags can also be set via environment variable or passed directly:

```bash
agentmgr --db /path/to/my.db --agents-dir /path/to/agents <command>
```

---

## The Council — Web UI

The Council is a multi-advisor AI system modeled on a presidential cabinet. You bring a topic or decision; the Secretary selects the right advisors, runs the deliberation, and delivers a synthesized recommendation.

### Starting the server

```bash
agentmgr-web
```

Opens at **http://localhost:8000**. The server reloads automatically when you edit agent YAML files.

### Starting a session

1. Click **New Session** in the sidebar (or visit `/`).
2. Type your brief in the text box — a question, decision, situation, or anything you want perspective on.
3. Hit **Send**.

The Secretary will read your brief and may ask a clarifying question if it needs more context. Answer it to sharpen the focus. After at most three exchanges the Secretary locks in a summary and convenes the council.

### The deliberation

Once the brief is finalized you'll see the deliberation unfold in real time:

- **Advisor panel** — the Secretary announces which advisors have been selected and explains why each one was chosen for this topic.
- **Advisor responses** — each advisor speaks in turn. Every advisor sees the responses of those who spoke before them, so later advisors can build on or challenge earlier points.
- **Synthesis** — the Secretary reads all advisor input and delivers a final recommendation that weighs and integrates their perspectives.

### Silent mode

Toggle **Silent mode** before submitting your brief. In silent mode the individual advisor responses are hidden and only the Secretary's final synthesis is shown. Useful when you want a clean answer without the deliberation thread.

### Managing advisors (Hire / Fire)

Click **Advisors** in the sidebar to open the advisor roster.

**Hire a new advisor:**
1. Click **Hire Advisor**.
2. Fill in the name (lowercase letters, digits, underscores — e.g. `finance_expert`), a short description, and the system prompt that defines the advisor's perspective and expertise.
3. Click **Hire**. The advisor YAML is written to the `agents/` directory and is immediately available.

**Fire an advisor:**
Click the **Fire** button on any advisor card. The advisor is archived (not deleted) so past sessions that referenced them remain intact. Archived advisors do not appear in the roster and are not selected for new sessions.

### Browsing past sessions

Past sessions appear in the **sidebar** under the New Session button, ordered by most recent. Click any session to replay the full deliberation thread — brief, advisor selections, each advisor's response, and the synthesis.

### Bundled advisors

| Advisor | Role |
|---|---|
| `planner` | Strategic planning and prioritization |
| `devil` | Devil's advocate — challenges assumptions |
| `health` | Physical and mental wellbeing |
| `career` | Career growth and professional decisions |
| `creative` | Creative thinking and lateral approaches |
| `relationships` | Interpersonal dynamics and communication |
| `decider` | Final decision frameworks when you're stuck |
| `researcher` | Research and fact-finding |
| `writer` | Communication and writing |
| `summarizer` | Compression and clarity |
| `critic` | Critical review and feedback |

---

## The Council — CLI

Run a council session without the browser:

```bash
agentmgr council "Should I move to a new city for this opportunity?"
```

The Secretary will ask clarifying questions in the terminal, then run the deliberation and print each advisor's response followed by the synthesis.

```bash
agentmgr council --silent "Evaluate this business idea"   # synthesis only
agentmgr council --no-brief "Quick take on remote work"   # skip clarification
```

---

## Defining agents

Each agent is a YAML file in the `agents/` directory.

```yaml
# agents/my_agent.yaml
name: my_agent
description: "What this agent does in one sentence."
system_prompt: |
  You are a ... Your job is to ...
  Use a clear, direct style.

# Optional — these are the defaults:
model: claude-opus-4-6
max_tokens: 4096
temperature: 1.0
tags: [example, custom]

meta:           # arbitrary key/value, ignored by the runner
  owner: alex
  intent: analysis
```

Drop any `.yaml` file in `agents/` and it's automatically available. No registration step needed.

### Bundled agents

| Agent | Description | Model |
|---|---|---|
| `researcher` | Researches a topic and returns a structured summary with key facts | claude-opus-4-6 |
| `writer` | Drafts polished prose — blog posts, emails, docs — from a brief | claude-opus-4-6 |
| `summarizer` | Compresses long text into a tight TL;DR + bullet points | claude-haiku-4-5 |
| `critic` | Reviews writing or plans and returns specific, actionable feedback | claude-opus-4-6 |
| `planner` | Strategic planning, roadmaps, and prioritization | claude-opus-4-6 |
| `devil` | Devil's advocate — challenges assumptions and stress-tests ideas | claude-opus-4-6 |
| `health` | Physical and mental wellbeing perspective | claude-opus-4-6 |
| `career` | Career growth, professional strategy, and workplace decisions | claude-opus-4-6 |
| `creative` | Lateral thinking and creative reframing | claude-opus-4-6 |
| `relationships` | Interpersonal dynamics and communication | claude-opus-4-6 |
| `decider` | Decision frameworks for when you're stuck | claude-opus-4-6 |

---

## Commands

### `agents`

```bash
agentmgr agents list              # list all defined agents
agentmgr agents show researcher   # print full details for one agent
```

### `run`

Run one agent immediately and print the response:

```bash
agentmgr run researcher "What caused the 2008 financial crisis?"
```

Run multiple agents **in parallel** (alternating agent/message pairs):

```bash
agentmgr run researcher "AI trends in 2026" \
         --parallel \
         writer "Write a blog post about AI trends" \
         summarizer "Large language models and their applications"
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--parallel` | off | Treat remaining args as additional agent/message pairs |
| `--workers N` | 5 | Max concurrent API calls |
| `--api-key KEY` | env | Anthropic API key (overrides .env) |

### `queue`

Submit tasks to the queue for later batch execution:

```bash
agentmgr queue submit researcher "Topic 1"
agentmgr queue submit writer "Write about topic 2" --priority 10
agentmgr queue submit summarizer "Long text to summarize..."

agentmgr queue status        # pending/running/completed/failed counts
agentmgr queue run           # drain the queue in parallel
agentmgr queue run --workers 10 --batch 50
```

Higher `--priority` tasks run first. Default priority is 0.

### `logs`

```bash
agentmgr logs list                       # 20 most recent runs
agentmgr logs list --agent researcher    # filter by agent
agentmgr logs list --status failed       # filter by status
agentmgr logs list --limit 100

agentmgr logs show <run_id>              # full output for one run
agentmgr logs show abc123               # prefix match works too
```

### `status`

```bash
agentmgr status    # task queue counts + total token usage
```

### `council`

Run a full Secretary-led council session in the terminal:

```bash
agentmgr council "Should I take on a co-founder?"
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--silent` | off | Show synthesis only — suppress advisor responses |
| `--no-brief` | off | Skip clarification round, use message as-is |

### `agents delete`

Archive an advisor (soft-delete — preserves past session history):

```bash
agentmgr agents delete my_agent
```

---

## Project structure

```
agent-manager/
├── .env.example              # copy to .env and add your API key
├── requirements.txt
├── setup.py
├── agents/                   # agent YAML definitions — add yours here
│   ├── researcher.yaml
│   ├── writer.yaml
│   ├── summarizer.yaml
│   ├── critic.yaml
│   ├── planner.yaml
│   ├── devil.yaml
│   ├── health.yaml
│   ├── career.yaml
│   ├── creative.yaml
│   ├── relationships.yaml
│   └── decider.yaml
└── agent_manager/
    ├── models.py             # AgentDef, Task, Run, Session, SessionMessage dataclasses
    ├── store.py              # SQLite persistence (tasks, runs, sessions, messages)
    ├── agent_loader.py       # YAML → AgentDef loader
    ├── executor.py           # async parallel runner (Anthropic SDK)
    ├── secretary.py          # Council orchestrator — brief, select, deliberate, synthesize
    ├── queue.py              # queue drain logic
    ├── cli.py                # Click CLI entry point (agentmgr + council command)
    └── web/
        ├── app.py            # FastAPI app with SSE streaming (agentmgr-web)
        └── templates/        # Jinja2 HTML templates (dark theme)
            ├── base.html
            ├── index.html
            ├── session.html
            └── agents.html
```

---

## How it works

1. **Agent definitions** are loaded from YAML files at runtime — no code changes needed to add or modify an agent.
2. **Tasks** are stored in a local SQLite database (`agent_manager.db`) with status tracking (`pending → running → completed/failed`).
3. **Execution** uses `asyncio` + `anthropic.AsyncAnthropic` to run multiple agents concurrently, capped by `--workers`.
4. **Runs** are immutably logged with full input/output, token usage, and duration for every execution.

### How The Council works

1. **Brief** — the Secretary reads your message and decides whether it has enough context. If not, it asks one clarifying question (up to three rounds).
2. **Select** — the Secretary evaluates every available advisor and picks the subset most relevant to the brief, with a short rationale for each selection.
3. **Deliberate** — selected advisors respond sequentially. Each advisor receives the full brief plus every prior advisor's response, enabling them to build on, challenge, or reframe earlier points.
4. **Synthesize** — the Secretary reads all advisor input and writes a final recommendation that weighs and integrates their perspectives.

Sessions are stored in SQLite and fully replayable from the web UI.

---

## Security

- API keys are read from the environment (`.env` or shell) — never hardcoded.
- `agent_manager.db` is excluded from git — it may contain your prompts and responses.
- `.env` is excluded from git.
- See `.gitignore` for the full exclusion list.

---

## License

MIT
