"""
CLI entry point.  Install with `pip install -e .` then use `agentmgr`.

Commands:
  agents list              — list all agent definitions
  agents show <name>       — print agent details
  run <agent> <message>    — run one agent immediately
  run --parallel …         — run multiple agents in parallel (see --help)
  queue submit <agent> <msg>  — add task to queue
  queue run                — drain the queue
  queue status             — show pending/running/completed/failed counts
  logs                     — list recent runs
  logs show <run_id>       — print full output for a run
  status                   — overall system stats
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

load_dotenv()

console = Console()

# ------------------------------------------------------------------ helpers

def _get_store(db: str) -> "Store":
    from .store import Store
    # Resolve relative to CWD so the same db file is used regardless of invocation path
    return Store(Path(db).resolve())


def _get_agents(agents_dir: str) -> dict:
    from .agent_loader import load_agents_dir
    return load_agents_dir(agents_dir)


def _short(text: Optional[str], n: int = 80) -> str:
    if text is None:
        return "—"
    text = text.replace("\n", " ")
    return text[:n] + "…" if len(text) > n else text


# ------------------------------------------------------------------ root

@click.group()
@click.option(
    "--db",
    default="agent_manager.db",
    envvar="AGENTMGR_DB",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option(
    "--agents-dir",
    default="agents",
    envvar="AGENTMGR_AGENTS_DIR",
    show_default=True,
    help="Directory containing agent YAML definitions.",
)
@click.pass_context
def cli(ctx: click.Context, db: str, agents_dir: str) -> None:
    """Agent Manager — run and manage multiple AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["agents_dir"] = agents_dir


# ================================================================== agents

@cli.group()
def agents() -> None:
    """Manage agent definitions."""


@agents.command("list")
@click.pass_context
def agents_list(ctx: click.Context) -> None:
    """List all agent definitions."""
    agent_map = _get_agents(ctx.obj["agents_dir"])
    if not agent_map:
        console.print("[yellow]No agents found in agents/ directory.[/yellow]")
        return

    table = Table(title="Agents", show_lines=True)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Model", style="dim")
    table.add_column("Tags", style="dim")

    for name, a in sorted(agent_map.items()):
        table.add_row(
            name,
            a.description,
            a.model,
            ", ".join(a.tags) or "—",
        )
    console.print(table)


@agents.command("show")
@click.argument("name")
@click.pass_context
def agents_show(ctx: click.Context, name: str) -> None:
    """Show full details for a single agent."""
    agent_map = _get_agents(ctx.obj["agents_dir"])
    agent = agent_map.get(name)
    if agent is None:
        console.print(f"[red]Agent '{name}' not found.[/red]")
        raise SystemExit(1)

    console.print(Panel(
        f"[bold]{agent.name}[/bold]\n\n"
        f"[dim]Description:[/dim]  {agent.description}\n"
        f"[dim]Model:[/dim]        {agent.model}\n"
        f"[dim]Max tokens:[/dim]   {agent.max_tokens}\n"
        f"[dim]Temperature:[/dim]  {agent.temperature}\n"
        f"[dim]Tags:[/dim]         {', '.join(agent.tags) or '—'}\n\n"
        f"[bold]System Prompt:[/bold]\n{agent.system_prompt}",
        title=f"Agent: {agent.name}",
        expand=False,
    ))


# ================================================================== run

@cli.command("run")
@click.argument("agent_name")
@click.argument("message", nargs=-1, required=True)
@click.option("--parallel", is_flag=True, help="Treat args as alternating agent/message pairs.")
@click.option("--workers", default=5, show_default=True, help="Max parallel workers.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, help="Anthropic API key.")
@click.pass_context
def run_cmd(
    ctx: click.Context,
    agent_name: str,
    message: tuple,
    parallel: bool,
    workers: int,
    api_key: Optional[str],
) -> None:
    """
    Run one agent immediately and print the response.

    With --parallel, treat AGENT_NAME MESSAGE as the first pair and
    subsequent positional args as alternating agent/message pairs:

      agentmgr run researcher "AI trends" --parallel writer "Write a post" summarizer "Big data"

    (The first positional pair is always agent + message; --parallel
    allows you to append more agent/message pairs as extra MESSAGE args.)
    """
    from .agent_loader import load_agents_dir
    from .executor import make_client, run_parallel
    from .models import Task
    from .store import Store

    store = Store(ctx.obj["db"])
    agent_map = load_agents_dir(ctx.obj["agents_dir"])
    client = make_client(api_key)

    if parallel:
        # Flatten: [agent_name, *message] into pairs
        all_args = [agent_name] + list(message)
        if len(all_args) % 2 != 0:
            console.print("[red]--parallel requires an even number of agent+message pairs.[/red]")
            raise SystemExit(1)
        pairs = [(all_args[i], all_args[i + 1]) for i in range(0, len(all_args), 2)]
        tasks = [Task(agent_name=a, user_message=m) for a, m in pairs]
    else:
        tasks = [Task(agent_name=agent_name, user_message=" ".join(message))]

    # Validate agents exist
    for task in tasks:
        if task.agent_name not in agent_map:
            console.print(f"[red]Unknown agent: '{task.agent_name}'[/red]")
            console.print(f"Available: {', '.join(sorted(agent_map))}")
            raise SystemExit(1)

    console.print(f"[bold]Running {len(tasks)} agent(s)…[/bold]\n")

    completed_count = 0

    async def on_done(run) -> None:
        nonlocal completed_count
        completed_count += 1
        if run.status == "completed":
            console.print(Panel(
                run.response or "",
                title=f"[green]{run.agent_name}[/green] ({run.duration_seconds:.1f}s  "
                      f"{run.input_tokens}↑ {run.output_tokens}↓ tokens)",
                expand=False,
            ))
        else:
            console.print(Panel(
                f"[red]{run.error}[/red]",
                title=f"[red]{run.agent_name} — FAILED[/red]",
                expand=False,
            ))

    runs = asyncio.run(
        run_parallel(
            client=client,
            agent_map=agent_map,
            tasks=tasks,
            store=store,
            max_concurrency=workers,
            on_complete=on_done,
        )
    )

    ok = sum(1 for r in runs if r.status == "completed")
    fail = sum(1 for r in runs if r.status == "failed")
    console.print(f"\n[dim]Done — {ok} completed, {fail} failed[/dim]")


# ================================================================== queue

@cli.group()
def queue() -> None:
    """Manage the task queue."""


@queue.command("submit")
@click.argument("agent_name")
@click.argument("message", nargs=-1, required=True)
@click.option("--priority", default=0, show_default=True, help="Higher runs sooner.")
@click.pass_context
def queue_submit(ctx: click.Context, agent_name: str, message: tuple, priority: int) -> None:
    """Add a task to the queue."""
    from .queue import submit
    store = _get_store(ctx.obj["db"])
    task = submit(store, agent_name, " ".join(message), priority=priority)
    console.print(f"[green]✓ Queued task[/green] [dim]{task.id}[/dim]  agent=[bold]{agent_name}[/bold]")


@queue.command("run")
@click.option("--workers", default=5, show_default=True, help="Max parallel workers.")
@click.option("--batch", default=20, show_default=True, help="Tasks per batch.")
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None)
@click.pass_context
def queue_run(ctx: click.Context, workers: int, batch: int, api_key: Optional[str]) -> None:
    """Drain all pending tasks from the queue."""
    from .queue import drain
    store = _get_store(ctx.obj["db"])
    result = drain(
        store=store,
        agents_dir=ctx.obj["agents_dir"],
        max_concurrency=workers,
        batch_size=batch,
        api_key=api_key,
    )
    console.print(
        f"\n[bold]Queue drained.[/bold]  "
        f"[green]{result['completed']} completed[/green]  "
        f"[red]{result['failed']} failed[/red]"
    )


@queue.command("status")
@click.pass_context
def queue_status(ctx: click.Context) -> None:
    """Show pending/running/completed/failed task counts."""
    store = _get_store(ctx.obj["db"])
    stats = store.stats()
    t = stats["tasks"]

    table = Table(title="Queue Status", show_header=False)
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Pending",   f"[yellow]{t.get('pending', 0)}[/yellow]")
    table.add_row("Running",   f"[blue]{t.get('running', 0)}[/blue]")
    table.add_row("Completed", f"[green]{t.get('completed', 0)}[/green]")
    table.add_row("Failed",    f"[red]{t.get('failed', 0)}[/red]")
    console.print(table)


# ================================================================== logs

@cli.group()
def logs() -> None:
    """View run history."""


@logs.command("list")
@click.option("--agent", default=None, help="Filter by agent name.")
@click.option("--status", default=None, type=click.Choice(["completed", "failed"]))
@click.option("--limit", default=20, show_default=True)
@click.pass_context
def logs_list(ctx: click.Context, agent: Optional[str], status: Optional[str], limit: int) -> None:
    """List recent runs."""
    store = _get_store(ctx.obj["db"])
    runs = store.list_runs(agent_name=agent, status=status, limit=limit)

    if not runs:
        console.print("[dim]No runs found.[/dim]")
        return

    table = Table(title="Recent Runs", show_lines=False)
    table.add_column("ID",       style="dim", no_wrap=True, max_width=12)
    table.add_column("Agent",    style="bold cyan")
    table.add_column("Status",   no_wrap=True)
    table.add_column("Tokens ↑↓", justify="right")
    table.add_column("Duration",  justify="right")
    table.add_column("Message",  max_width=40)
    table.add_column("Created",   style="dim", no_wrap=True)

    for r in runs:
        status_str = (
            "[green]✓ completed[/green]" if r.status == "completed"
            else "[red]✗ failed[/red]"
        )
        table.add_row(
            r.id[:8],
            r.agent_name,
            status_str,
            f"{r.input_tokens}/{r.output_tokens}",
            f"{r.duration_seconds:.1f}s",
            _short(r.user_message, 40),
            r.created_at[:19].replace("T", " "),
        )
    console.print(table)


@logs.command("show")
@click.argument("run_id")
@click.pass_context
def logs_show(ctx: click.Context, run_id: str) -> None:
    """Print full output for a specific run (prefix match on ID)."""
    store = _get_store(ctx.obj["db"])
    # Support short-prefix lookup
    run = store.get_run(run_id)
    if run is None:
        # Try prefix match
        all_runs = store.list_runs(limit=1000)
        matches = [r for r in all_runs if r.id.startswith(run_id)]
        if not matches:
            console.print(f"[red]Run '{run_id}' not found.[/red]")
            raise SystemExit(1)
        run = matches[0]

    color = "green" if run.status == "completed" else "red"
    console.print(Panel(
        run.response or run.error or "—",
        title=(
            f"[{color}]{run.status.upper()}[/{color}]  "
            f"[bold]{run.agent_name}[/bold]  "
            f"[dim]{run.id}[/dim]\n"
            f"[dim]{run.created_at[:19]}  "
            f"{run.input_tokens}↑ {run.output_tokens}↓ tokens  "
            f"{run.duration_seconds:.2f}s[/dim]"
        ),
        expand=False,
    ))
    console.print(f"\n[dim]Message:[/dim] {run.user_message}")


# ================================================================== status

@cli.command("status")
@click.pass_context
def system_status(ctx: click.Context) -> None:
    """Show overall system stats."""
    store = _get_store(ctx.obj["db"])
    stats = store.stats()
    t = stats["tasks"]
    r = stats["runs"]

    console.print(Panel(
        f"[bold]Tasks[/bold]\n"
        f"  Pending:   [yellow]{t.get('pending', 0)}[/yellow]\n"
        f"  Running:   [blue]{t.get('running', 0)}[/blue]\n"
        f"  Completed: [green]{t.get('completed', 0)}[/green]\n"
        f"  Failed:    [red]{t.get('failed', 0)}[/red]\n\n"
        f"[bold]Runs[/bold]\n"
        f"  Total:           {r.get('total_runs') or 0}\n"
        f"  Input tokens:    {r.get('total_input_tokens') or 0:,}\n"
        f"  Output tokens:   {r.get('total_output_tokens') or 0:,}\n"
        f"  Avg duration:    {(r.get('avg_duration') or 0):.2f}s",
        title="Agent Manager Status",
        expand=False,
    ))


# ================================================================== entry

def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
