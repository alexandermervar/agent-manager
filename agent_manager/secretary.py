"""
Secretary — the orchestrator of The Council.

Stages:
  1. Brief      — back-and-forth with user until the request is clear
  2. Select     — LLM picks which council members to convene and explains why
  3. Deliberate — agents run sequentially; each sees all prior responses
  4. Synthesize — Secretary delivers final verdict
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator, Optional

import yaml
import anthropic

from .models import Session, SessionMessage, Task, _now
from .store import Store
from .executor import run_agent
from .agent_loader import load_agents_dir, load_agent_file


_BRIEF_SYSTEM = """\
You are the Secretary to a personal cabinet of advisors. Your role is to take a clear brief \
from the user before convening the council.

Evaluate whether you have enough context to brief the council. If not, ask one focused follow-up \
question — never more than one at a time.

Respond ONLY in valid JSON. No other text.
If sufficient: {"sufficient": true, "summary": "<2-3 sentence summary of the request>"}
If not:        {"sufficient": false, "question": "<one follow-up question>"}"""

_SELECT_SYSTEM = """\
You are the Secretary. Select which cabinet members to convene for this request.

Available members:
{roster}

User's request:
{summary}

Select 2-5 members most relevant to this request. If you need an advisor that is not in the \
roster, include them in "create" with a short role description — they will be hired on the spot.

Respond ONLY in valid JSON. No other text.
{{"selected": ["name1", "name2"], "rationale": "<one paragraph explaining choices>", \
"create": [{{"name": "snake_case_name", "role": "<what this advisor does>"}}]}}"""

_CREATE_AGENT_SYSTEM = """\
Generate a system prompt for a new cabinet advisor.

Name: {name}
Role: {role}

Respond ONLY in valid JSON. No other text.
{{"name": "{name}", "description": "<one sentence>", "system_prompt": "<detailed system prompt>", \
"tags": ["tag1", "tag2"]}}"""

_SYNTHESIZE_SYSTEM = """\
You are the Secretary. You have convened the cabinet and received their counsel.

Original request:
{summary}

Cabinet responses:
{responses}

Deliver a clear, actionable synthesis: your recommendation, key agreements and tensions among the \
advisors, and concrete next steps. Be direct and decisive. No filler."""


class Secretary:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        agents_dir: str,
        store: Store,
    ) -> None:
        self.client = client
        self.agents_dir = Path(agents_dir)
        self.store = store

    # ------------------------------------------------------------------ public

    async def evaluate_brief(self, session_id: str, user_message: str) -> dict:
        """
        Evaluate whether the brief is sufficient to convene the council.
        Saves user message (and secretary question if any) to DB.

        Returns:
          {"sufficient": True,  "summary": "..."}
          {"sufficient": False, "question": "..."}
        """
        seq = self.store.next_seq(session_id)

        self.store.add_message(SessionMessage(
            session_id=session_id,
            role="user",
            stage="brief",
            content=user_message,
            seq=seq,
        ))
        seq += 1

        # Build conversation history from all prior brief messages
        prior = [
            m for m in self.store.get_messages(session_id)
            if m.stage == "brief" and m.role in ("user", "secretary")
        ]
        history = [
            {"role": "user" if m.role == "user" else "assistant", "content": m.content}
            for m in prior
        ]

        raw = await self._llm(_BRIEF_SYSTEM, history)
        result = json.loads(raw)

        if not result.get("sufficient"):
            self.store.add_message(SessionMessage(
                session_id=session_id,
                role="secretary",
                stage="brief",
                content=result["question"],
                seq=seq,
            ))

        return result

    async def run_council(
        self,
        session_id: str,
        brief_summary: str,
        silent_mode: bool = False,
    ) -> AsyncIterator[dict]:
        """
        Async generator: runs Select → Deliberate → Synthesize and yields SSE-ready event dicts.

        Event types:
          council_selected  — {"type", "agents": [...], "rationale": "..."}
          agent_start       — {"type", "agent_name", "index", "total"}
          agent_complete    — {"type", "agent_name", "response", "index", "total"}
                              (in silent mode: no "response" key)
          synthesis         — {"type", "content": "..."}
          session_complete  — {"type"}
        """
        agent_map = load_agents_dir(self.agents_dir)
        seq = self.store.next_seq(session_id)

        # ── Select ──────────────────────────────────────────────────────────
        self.store.update_session(session_id, status="selecting")

        roster = "\n".join(
            f"- {name}: {a.description}" for name, a in sorted(agent_map.items())
        )
        select_prompt = _SELECT_SYSTEM.format(roster=roster, summary=brief_summary)
        raw = await self._llm(
            select_prompt, [{"role": "user", "content": "Select the council members."}]
        )
        selection = json.loads(raw)

        # Hire any missing agents
        for spec in selection.get("create", []):
            agent = await self._create_agent(spec["name"], spec["role"])
            agent_map[agent.name] = agent

        selected_names = [n for n in selection["selected"] if n in agent_map]
        rationale = selection.get("rationale", "")

        self.store.add_message(SessionMessage(
            session_id=session_id,
            role="system",
            stage="select",
            content=json.dumps({"selected": selected_names, "rationale": rationale}),
            seq=seq,
        ))
        seq += 1

        yield {"type": "council_selected", "agents": selected_names, "rationale": rationale}

        # ── Deliberate ──────────────────────────────────────────────────────
        self.store.update_session(session_id, status="deliberating")
        prior_responses: list[dict] = []

        for i, agent_name in enumerate(selected_names):
            agent = agent_map[agent_name]
            yield {
                "type": "agent_start",
                "agent_name": agent_name,
                "index": i + 1,
                "total": len(selected_names),
            }

            context = f"Request: {brief_summary}"
            if prior_responses:
                prior_text = "\n\n".join(
                    f"[{r['agent']}]: {r['response']}" for r in prior_responses
                )
                context += f"\n\nPrior advisor input:\n{prior_text}"

            task = Task(
                agent_name=agent_name,
                user_message=context,
                metadata={"session_id": session_id},
            )
            run = await run_agent(self.client, agent, task, self.store)
            response_text = run.response or run.error or ""

            prior_responses.append({"agent": agent_name, "response": response_text})

            self.store.add_message(SessionMessage(
                session_id=session_id,
                role="agent",
                agent_name=agent_name,
                stage="deliberate",
                content=response_text,
                seq=seq,
            ))
            seq += 1

            if silent_mode:
                yield {
                    "type": "agent_complete",
                    "agent_name": agent_name,
                    "index": i + 1,
                    "total": len(selected_names),
                }
            else:
                yield {
                    "type": "agent_complete",
                    "agent_name": agent_name,
                    "response": response_text,
                    "index": i + 1,
                    "total": len(selected_names),
                }

        # ── Synthesize ──────────────────────────────────────────────────────
        responses_text = "\n\n".join(
            f"[{r['agent']}]: {r['response']}" for r in prior_responses
        )
        synthesis_prompt = _SYNTHESIZE_SYSTEM.format(
            summary=brief_summary, responses=responses_text
        )
        synthesis = await self._llm(
            synthesis_prompt,
            [{"role": "user", "content": "Deliver your synthesis."}],
        )

        self.store.add_message(SessionMessage(
            session_id=session_id,
            role="secretary",
            stage="synthesis",
            content=synthesis,
            seq=seq,
        ))
        self.store.update_session(session_id, status="complete", completed_at=_now())

        yield {"type": "synthesis", "content": synthesis}
        yield {"type": "session_complete"}

    # ------------------------------------------------------------------ private

    async def _llm(self, system: str, messages: list[dict]) -> str:
        response = await self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    async def _create_agent(self, name: str, role: str):
        """Generate a YAML for a new agent, write it to agents_dir, and return the AgentDef."""
        prompt = _CREATE_AGENT_SYSTEM.format(name=name, role=role)
        raw = await self._llm(
            prompt, [{"role": "user", "content": "Generate the agent definition."}]
        )
        data = json.loads(raw)

        agent_data = {
            "name": data.get("name", name),
            "description": data.get("description", role),
            "system_prompt": data["system_prompt"],
            "model": "claude-opus-4-6",
            "max_tokens": 4096,
            "temperature": 1.0,
            "tags": data.get("tags", ["council"]),
        }

        path = self.agents_dir / f"{name}.yaml"
        with open(path, "w") as f:
            yaml.dump(agent_data, f, default_flow_style=False, allow_unicode=True)

        return load_agent_file(path)
