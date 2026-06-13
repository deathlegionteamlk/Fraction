"""FastAPI server for Fraction.

Routes:
  GET  /                  → static frontend
  GET  /api/health        → liveness probe
  GET  /api/config        → safe public view of the loaded config
  GET  /api/memory        → long-term memory entries
  POST /api/goal          → start a goal run (returns session id)
  GET  /api/stream/{sid}  → SSE stream of events for a session
  POST /api/feedback      → user thumbs up/down on a deliverable
  GET  /api/deliverables  → list past deliverables
  GET  /api/deliverable/{id} → fetch a deliverable
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import Orchestrator
from .config import get_config
from .memory import MemoryManager
from .models import ModelRouter
from .tools import build_default_registry

log = logging.getLogger("fraction.server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)


# ---- app + singletons -------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
DELIVERABLES_DIR = REPO_ROOT / "deliverables"
DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)

cfg = get_config()
router = ModelRouter(cfg)
tools = build_default_registry()
memory = MemoryManager()
orch = Orchestrator(cfg=cfg, router=router, tools=tools, memory=memory)


# session_id -> asyncio.Queue
_event_queues: dict[str, asyncio.Queue] = {}
_session_runs: dict[str, dict[str, Any]] = {}


app = FastAPI(title="Fraction", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- request models ---------------------------------------------------------


class GoalRequest(BaseModel):
    goal: str
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    session_id: str
    deliverable_id: str
    rating: int        # 1..5
    comment: str = ""


# ---- core endpoints ---------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": cfg.app.name,
        "owner": cfg.app.owner,
        "providers": [
            {"name": n, "models": p.models, "default": p.default, "free": p.free}
            for n, p in cfg.providers.items()
            if p.enabled
        ],
    }


@app.get("/api/config")
async def public_config() -> dict[str, Any]:
    """Return a redacted, public-safe view of the config (no API keys)."""
    return {
        "app": cfg.app.model_dump(),
        "providers": [
            {
                "name": n,
                "enabled": p.enabled,
                "default": p.default,
                "models": p.models,
                "free": p.free,
                "has_key": bool(p.api_key and "${" not in p.api_key and p.api_key != "ollama"),
                "base_url": p.base_url,
            }
            for n, p in cfg.providers.items()
        ],
        "roles": cfg.roles,
        "tools": {
            "web_search": cfg.tools.web_search.enabled,
            "web_fetch": cfg.tools.web_fetch.enabled,
            "code_exec": cfg.tools.code_exec.enabled,
            "file_io": cfg.tools.file_io.enabled,
        },
    }


@app.get("/api/memory")
async def list_memory(limit: int = 20) -> dict[str, Any]:
    return {
        "episodes": memory.long.recent(limit),
        "facts": memory.facts()[:limit],
        "total_items": len(memory.long._items),
    }


@app.post("/api/goal")
async def start_goal(req: GoalRequest) -> dict[str, Any]:
    sid = req.session_id or uuid.uuid4().hex[:12]
    if sid in _event_queues and not _event_queues[sid].empty():
        raise HTTPException(409, detail=f"Session {sid} is already running")
    _event_queues[sid] = asyncio.Queue()
    _session_runs[sid] = {
        "goal": req.goal,
        "started_at": time.time(),
        "deliverables": [],
    }
    # background task
    asyncio.create_task(_run_goal(sid, req.goal))
    return {"session_id": sid}


async def _run_goal(sid: str, goal: str) -> None:
    q = _event_queues[sid]
    deliverable_text: str | None = None
    try:
        async for ev in orch.run(goal, sid):
            await q.put(ev)
            if ev.type == "deliverable":
                deliverable_text = ev.content
                did = ev.data.get("id", uuid.uuid4().hex[:12])
                fp = DELIVERABLES_DIR / f"{did}.md"
                fp.write_text(ev.content, encoding="utf-8")
                _session_runs[sid]["deliverables"].append({
                    "id": did, "text": ev.content[:300], "path": str(fp),
                })
    except Exception as e:  # noqa: BLE001
        log.exception("run failed")
        await q.put({"type": "error", "content": str(e), "ts": time.time()})
    finally:
        await q.put({"type": "__end__", "ts": time.time()})


@app.get("/api/stream/{sid}")
async def stream(sid: str, request: Request):
    if sid not in _event_queues:
        raise HTTPException(404, detail="Unknown session")

    async def gen():
        q = _event_queues[sid]
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # heartbeat so proxies don't drop the connection
                yield ": ping\n\n"
                continue
            if isinstance(ev, dict):
                data = ev
            else:
                data = ev.to_dict()
            if data.get("type") == "__end__":
                yield "event: end\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(data, default=str)}\n\n"
            if await request.is_disconnected():
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest) -> dict[str, Any]:
    memory.remember_episode(
        goal=f"feedback for {req.deliverable_id}",
        summary=f"rating={req.rating} comment={req.comment}",
        success=req.rating >= 4,
    )
    return {"ok": True}


@app.get("/api/deliverables")
async def list_deliverables() -> dict[str, Any]:
    out = []
    for fp in sorted(DELIVERABLES_DIR.glob("*.md"), reverse=True):
        out.append({
            "id": fp.stem,
            "size": fp.stat().st_size,
            "modified": fp.stat().st_mtime,
            "preview": fp.read_text(encoding="utf-8", errors="replace")[:300],
        })
    return {"items": out}


@app.get("/api/deliverable/{did}")
async def get_deliverable(did: str) -> dict[str, Any]:
    fp = DELIVERABLES_DIR / f"{did}.md"
    if not fp.exists():
        raise HTTPException(404)
    return {"id": did, "content": fp.read_text(encoding="utf-8")}


# ---- static frontend --------------------------------------------------------


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index() -> HTMLResponse:
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Fraction</h1><p>frontend/index.html not found</p>")


@app.get("/favicon.ico")
async def favicon():
    fp = FRONTEND_DIR / "favicon.ico"
    if fp.exists():
        return FileResponse(fp)
    return JSONResponse({}, status_code=204)
