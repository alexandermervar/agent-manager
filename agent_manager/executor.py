"""
Parallel agent executor.

Uses the Anthropic AsyncAnthropic client + asyncio.Semaphore
to run multiple agents concurrently with a configurable concurrency cap.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import anthropic

from .models import AgentDef, Run, Task
from .store import Store


async def run_agent(
    client: anthropic.AsyncAnthropic,
    agent: AgentDef,
    task: Task,
    store: Store,
) -> Run:
    """
    Execute one agent against one task.
    Writes the resulting Run to the store and updates the Task status.
    """
    start = time.monotonic()
    run = Run(
        task_id=task.id,
        agent_name=agent.name,
        user_message=task.user_message,
        model=agent.model,
        status="running",
    )

    try:
        message = await client.messages.create(
            model=agent.model,
            max_tokens=agent.max_tokens,
            temperature=agent.temperature,
            system=agent.system_prompt,
            messages=[{"role": "user", "content": task.user_message}],
        )
        run.response = message.content[0].text if message.content else ""
        run.input_tokens = message.usage.input_tokens
        run.output_tokens = message.usage.output_tokens
        run.status = "completed"

        task.status = "completed"
        task.run_id = run.id

    except Exception as exc:  # noqa: BLE001
        run.error = str(exc)
        run.status = "failed"
        task.status = "failed"
        task.error = str(exc)

    finally:
        run.duration_seconds = time.monotonic() - start
        from .models import _now
        task.completed_at = _now()
        store.insert_run(run)
        store.upsert_task(task)

    return run


async def run_parallel(
    client: anthropic.AsyncAnthropic,
    agent_map: dict[str, AgentDef],
    tasks: list[Task],
    store: Store,
    max_concurrency: int = 5,
    on_complete=None,
) -> list[Run]:
    """
    Run a list of tasks in parallel, capped at `max_concurrency` simultaneous calls.

    `agent_map`   – dict of {agent_name: AgentDef}
    `on_complete` – optional async callback(run: Run) called after each task finishes
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(task: Task) -> Run:
        agent = agent_map.get(task.agent_name)
        if agent is None:
            # Mark immediately failed — unknown agent
            from .models import _now
            task.status = "failed"
            task.error = f"Unknown agent '{task.agent_name}'"
            task.completed_at = _now()
            store.upsert_task(task)
            run = Run(
                task_id=task.id,
                agent_name=task.agent_name,
                user_message=task.user_message,
                model="unknown",
                status="failed",
                error=task.error,
            )
            store.insert_run(run)
            if on_complete:
                await on_complete(run)
            return run

        async with semaphore:
            # Mark task as running in the store
            from .models import _now
            task.status = "running"
            task.started_at = _now()
            store.upsert_task(task)

            run = await run_agent(client, agent, task, store)

        if on_complete:
            await on_complete(run)
        return run

    return await asyncio.gather(*[_run_one(t) for t in tasks])


def make_client(api_key: Optional[str] = None) -> anthropic.AsyncAnthropic:
    """Create an AsyncAnthropic client, reading ANTHROPIC_API_KEY from env if not supplied."""
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    return anthropic.AsyncAnthropic(**kwargs)
