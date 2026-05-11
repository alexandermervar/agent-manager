# agent-manager

A Python CLI for defining, running, queuing, and logging multiple AI agents — each with its own system prompt, model, and configuration. Built on the [Anthropic Python SDK](https://github.com/anthropic/anthropic-sdk-python).

---

## What it does

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

# 3. Try it
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
│   └── critic.yaml
└── agent_manager/
    ├── models.py             # AgentDef, Task, Run dataclasses
    ├── store.py              # SQLite persistence (tasks + run history)
    ├── agent_loader.py       # YAML → AgentDef loader
    ├── executor.py           # async parallel runner (Anthropic SDK)
    ├── queue.py              # queue drain logic
    └── cli.py                # Click CLI entry point
```

---

## How it works

1. **Agent definitions** are loaded from YAML files at runtime — no code changes needed to add or modify an agent.
2. **Tasks** are stored in a local SQLite database (`agent_manager.db`) with status tracking (`pending → running → completed/failed`).
3. **Execution** uses `asyncio` + `anthropic.AsyncAnthropic` to run multiple agents concurrently, capped by `--workers`.
4. **Runs** are immutably logged with full input/output, token usage, and duration for every execution.

---

## Security

- API keys are read from the environment (`.env` or shell) — never hardcoded.
- `agent_manager.db` is excluded from git — it may contain your prompts and responses.
- `.env` is excluded from git.
- See `.gitignore` for the full exclusion list.

---

## License

MIT
