"""
Data models for the agent manager system.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class AgentDef:
    """
    Defines an agent's identity, prompt, and runtime config.
    Loaded from a YAML file in the agents/ directory.
    """
    name: str
    description: str
    system_prompt: str
    model: str = "claude-opus-4-6"
    max_tokens: int = 4096
    temperature: float = 1.0
    tags: list[str] = field(default_factory=list)
    # Optional metadata (arbitrary key/value from the YAML)
    meta: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        tags_str = ", ".join(self.tags) if self.tags else "—"
        return (
            f"[bold]{self.name}[/bold]\n"
            f"  {self.description}\n"
            f"  model={self.model}  max_tokens={self.max_tokens}  tags={tags_str}"
        )


@dataclass
class Task:
    """
    A unit of work: one agent + one user message to process.
    Lives in the task queue until executed.
    """
    agent_name: str
    user_message: str
    priority: int = 0                      # higher = runs sooner
    status: str = "pending"                # pending | running | completed | failed
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    run_id: Optional[str] = None           # linked Run after execution
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    """
    An immutable record of a completed (or failed) agent execution.
    Written to the store once the agent finishes.
    """
    task_id: str
    agent_name: str
    user_message: str
    model: str
    status: str                            # completed | failed
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now)
    response: Optional[str] = None
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """
    A Council session: one full Secretary interaction from brief to synthesis.
    """
    id: str = field(default_factory=_new_id)
    title: Optional[str] = None
    status: str = "briefing"        # briefing | selecting | deliberating | complete
    silent_mode: bool = False
    created_at: str = field(default_factory=_now)
    completed_at: Optional[str] = None


@dataclass
class SessionMessage:
    """
    One message in a Council session — from user, secretary, an agent, or the system.
    """
    session_id: str
    role: str                       # user | secretary | agent | system
    stage: str                      # brief | select | deliberate | synthesis
    content: str
    seq: int                        # ordering within the session
    id: str = field(default_factory=_new_id)
    agent_name: Optional[str] = None
    created_at: str = field(default_factory=_now)
