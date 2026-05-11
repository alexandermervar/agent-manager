"""
High-level task queue operations built on top of the Store.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .agent_loader import load_agents_dir
from .executor import make_client, run_parallel
from .models import Task
from .store import Store

console = Console()


def submit(
    store: Store,
    agent_name: str,
    user_message: str,
    priority: int = 0,
    metadata: Optional[dict[str, Any]] = None,
) -> Task:
    """Add a task to the pending queue and return it."""
    task = Task(
        agent_name=agent_name,
        user_message=user_message,
        priority=priority,
        metadata=metadata or {},
    )
    store.upsert_task(task)
    return task


def drain(
    store: Store,
    agents_dir: str,
    max_concurrency: int = 5,
    batch_size: int = 20,
    api_key: Optional[str] = None,
) -> dict:
    """
    Drain all pending tasks from the queue.
    Loads agent definitions from `agents_dir`, then runs tasks in parallel batches.
    Returns summary stats.
    """
    agent_map = load_agents_dir(agents_dir)
    client = make_client(api_key)

    total_completed = 0
    total_failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        while True:
            tasks = store.claim_pending_tasks(limit=batch_size)
            if not tasks:
                break

            task_id = progress.add_task(
                f"Running {len(tasks)} task(s)…", total=None
            )

            runs = asyncio.run(
                run_parallel(
                    client=client,
                    agent_map=agent_map,
                    tasks=tasks,
                    store=store,
                    max_concurrency=max_concurrency,
                )
            )

            completed = sum(1 for r in runs if r.status == "completed")
            failed = sum(1 for r in runs if r.status == "failed")
            total_completed += completed
            total_failed += failed

            progress.update(
                task_id,
                description=f"Batch done — {completed} completed, {failed} failed",
                completed=1,
                total=1,
            )

    return {"completed": total_completed, "failed": total_failed}
