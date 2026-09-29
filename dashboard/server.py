"""
FastAPI Dashboard Server with WebSocket Telemetry Broadcaster.

Serves the real-time Control Room UI and pushes simulation telemetry
to all connected browser clients via WebSocket.

Thread-safe design: the simulation loop in main_controller.py calls
``push_telemetry(data)`` from its own thread; this module forwards
the payload to the asyncio event loop running in the uvicorn thread.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES_DIR = os.path.join(_THIS_DIR, "templates")
_STATIC_DIR = os.path.join(_THIS_DIR, "static")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Green Corridor Control Room", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# ---------------------------------------------------------------------------
# Shared State for Scenario Control
# ---------------------------------------------------------------------------

class SharedState:
    def __init__(self):
        self.current_scenario = "scenario_b"
        self.needs_restart = False
        self.lock = threading.Lock()

shared_state = SharedState()



# ---------------------------------------------------------------------------
# WebSocket Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages active WebSocket connections and broadcasts JSON payloads."""

    def __init__(self):
        self._active: List[WebSocket] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        with self._lock:
            self._active.append(ws)

    def disconnect(self, ws: WebSocket):
        with self._lock:
            if ws in self._active:
                self._active.remove(ws)

    async def broadcast(self, data: dict):
        payload = json.dumps(data)
        with self._lock:
            clients = list(self._active)
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Thread-safe push function (called from the simulation thread)
# ---------------------------------------------------------------------------

def push_telemetry(data: dict):
    """
    Thread-safe telemetry push.  Call this from the simulation loop thread
    to send data to all connected WebSocket clients.
    """
    loop = manager._loop
    if loop is None or loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/set_scenario")
async def set_scenario(request: Request):
    data = await request.json()
    with shared_state.lock:
        shared_state.current_scenario = data.get("scenario", "scenario_b")
        shared_state.needs_restart = True
    return {"status": "success", "scenario": shared_state.current_scenario}


@app.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client doesn't send data
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Startup hook: capture the running event loop
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    manager.set_loop(asyncio.get_running_loop())
    print("  [DASHBOARD] Control Room ready at http://localhost:8000")


# ---------------------------------------------------------------------------
# Standalone launcher (for testing without main_controller)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
