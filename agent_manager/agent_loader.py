"""
Load AgentDef objects from YAML files.

Expected YAML format:
  name: researcher
  description: "Researches topics and summarises findings"
  system_prompt: |
    You are a thorough research assistant...
  model: claude-opus-4-6         # optional
  max_tokens: 4096               # optional
  temperature: 1.0               # optional
  tags: [research, summaries]    # optional
  meta:                          # optional arbitrary metadata
    owner: alex
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml

from .models import AgentDef


_DEFAULTS = dict(
    model="claude-opus-4-6",
    max_tokens=4096,
    temperature=1.0,
    tags=[],
    meta={},
)


def load_agent_file(path: Union[str, Path]) -> AgentDef:
    """Load a single YAML agent definition."""
    path = Path(path)
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data)}")
    for required in ("name", "description", "system_prompt"):
        if required not in data:
            raise ValueError(f"{path}: missing required field '{required}'")
    merged = {**_DEFAULTS, **data}
    return AgentDef(
        name=merged["name"],
        description=merged["description"],
        system_prompt=merged["system_prompt"],
        model=merged["model"],
        max_tokens=int(merged["max_tokens"]),
        temperature=float(merged["temperature"]),
        tags=list(merged.get("tags") or []),
        meta=dict(merged.get("meta") or {}),
    )


def load_agents_dir(directory: Union[str, Path]) -> dict[str, AgentDef]:
    """
    Load all *.yaml / *.yml files from `directory`.
    Returns a dict keyed by agent name.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Agents directory not found: {directory}")
    agents: dict[str, AgentDef] = {}
    yaml_files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    for path in yaml_files:
        try:
            agent = load_agent_file(path)
            agents[agent.name] = agent
        except Exception as exc:
            raise ValueError(f"Failed to load agent from {path}: {exc}") from exc
    return agents
