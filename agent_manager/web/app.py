"""
FastAPI web application for The Council.

Start with:
    agentmgr-web
    uvicorn agent_manager.web.app:app --reload
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import quote
from typing import Optional

import yaml as yaml_lib
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from ..agent_loader import load_agents_dir
from ..executor import make_client
from ..models import Session
from ..secretary import Secretary
from ..store import Store

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(store: Store, agents_dir: str) -> FastAPI:
    """
    Factory that creates the FastAPI app bound to a specific store and agents directory.
    Used directly in tests and by the `start` entry point.
    """
    app = FastAPI(title="The Council")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["fromjson"] = json.loads

    # ── Pages ────────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html")

    @app.post("/sessions")
    async def create_session(
        request: Request,
        message: str = Form(...),
        silent_mode: Optional[str] = Form(None),
    ) -> RedirectResponse:
        session = Session(silent_mode=bool(silent_mode))
        store.create_session(session)
        encoded = quote(message)
        return RedirectResponse(
            f"/sessions/{session.id}?first_message={encoded}", status_code=303
        )

    @app.get("/sessions", response_class=HTMLResponse)
    async def list_sessions(request: Request) -> HTMLResponse:
        sessions = store.list_sessions()
        return templates.TemplateResponse(
            request, "sessions.html", {"sessions": sessions}
        )

    @app.get("/sessions/{session_id}", response_class=HTMLResponse)
    async def session_view(
        request: Request, session_id: str, first_message: str = ""
    ) -> HTMLResponse:
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = store.get_messages(session_id)
        return templates.TemplateResponse(
            request,
            "session.html",
            {
                "session": session,
                "messages": messages,
                "first_message": first_message,
            },
        )

    # ── API: Brief ───────────────────────────────────────────────────────────

    @app.post("/sessions/{session_id}/brief")
    async def brief(session_id: str, request: Request) -> dict:
        """
        Handle one round of the brief exchange.
        Returns: {"sufficient": bool, "question"?: str, "summary"?: str}
        """
        body = await request.json()
        user_message = body.get("message", "").strip()
        if not user_message:
            raise HTTPException(status_code=400, detail="message is required")
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        client = make_client()
        secretary = Secretary(client, agents_dir, store)
        result = await secretary.evaluate_brief(session_id, user_message)
        return result

    # ── API: SSE Council Stream ──────────────────────────────────────────────

    @app.get("/sessions/{session_id}/stream")
    async def session_stream(session_id: str, summary: str = "") -> EventSourceResponse:
        """
        SSE stream that runs Select → Deliberate → Synthesize for a session.
        Query param `summary` is the brief summary produced by the brief stage.
        """
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        client = make_client()
        secretary = Secretary(client, agents_dir, store)

        async def event_generator():
            try:
                async for event in secretary.run_council(
                    session_id, summary, silent_mode=session.silent_mode
                ):
                    yield {
                        "event": event["type"],
                        "data": json.dumps(event),
                    }
            except Exception as exc:
                yield {
                    "event": "council_error",
                    "data": json.dumps({"type": "council_error", "detail": str(exc)}),
                }

        return EventSourceResponse(event_generator())

    # ── Agents ───────────────────────────────────────────────────────────────

    @app.get("/agents", response_class=HTMLResponse)
    async def agents_page(request: Request) -> HTMLResponse:
        agent_map = load_agents_dir(agents_dir)
        return templates.TemplateResponse(
            request,
            "agents.html",
            {"agents": list(agent_map.values())},
        )

    @app.post("/agents")
    async def create_agent_route(
        name: str = Form(...),
        description: str = Form(...),
        system_prompt: str = Form(...),
    ) -> RedirectResponse:
        agent_data = {
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "model": "claude-opus-4-6",
            "max_tokens": 4096,
            "temperature": 1.0,
            "tags": ["council"],
        }
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise HTTPException(status_code=422, detail="Agent name must be lowercase snake_case")
        path = Path(agents_dir) / f"{name}.yaml"
        with open(path, "w") as f:
            yaml_lib.dump(agent_data, f, default_flow_style=False, allow_unicode=True)
        return RedirectResponse("/agents", status_code=303)

    @app.delete("/agents/{name}")
    async def delete_agent_route(name: str) -> dict:
        safe = Path(name).name
        if not re.fullmatch(r"[a-z][a-z0-9_]*", safe):
            raise HTTPException(status_code=422, detail="Invalid agent name")
        src = Path(agents_dir) / f"{safe}.yaml"
        if not src.exists():
            raise HTTPException(status_code=404, detail=f"Agent '{safe}' not found")
        archived = Path(agents_dir) / "_archived"
        archived.mkdir(exist_ok=True)
        src.rename(archived / f"{safe}.yaml")
        return {"status": "archived", "name": safe}

    return app


# Module-level app instance for uvicorn (reads env vars)
app = create_app(
    store=Store(os.environ.get("AGENTMGR_DB", "agent_manager.db")),
    agents_dir=os.environ.get("AGENTMGR_AGENTS_DIR", "agents"),
)


def start() -> None:
    """Entry point for `agentmgr-web`."""
    import uvicorn
    uvicorn.run(
        "agent_manager.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
