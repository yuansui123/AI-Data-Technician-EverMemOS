"""Web interface — FastAPI app with WebSocket for real-time event streaming.

Run via:  python main.py --web
Opens at: http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

if TYPE_CHECKING:
    pass

app = FastAPI(title="AI Data Technician")

# ── Connection manager ─────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active = [w for w in self.active if w is not ws]

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()


# ── REST API ───────────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects():
    import config
    projects_dir = Path(config.PROJECTS_DIR)
    if not projects_dir.exists():
        return ["default"]
    dirs = sorted(p.name for p in projects_dir.iterdir() if p.is_dir())
    return dirs if dirs else ["default"]


@app.post("/api/projects/{name}")
async def create_project(name: str):
    import config
    safe = re.sub(r"[^\w\-]", "_", name.strip()) or "unnamed"
    (Path(config.PROJECTS_DIR) / safe).mkdir(parents=True, exist_ok=True)
    return {"name": safe}


@app.get("/files")
async def serve_file(path: str):
    """Serve image files inside the projects directory."""
    import config
    full_path = Path(path).resolve()
    projects_root = Path(config.PROJECTS_DIR).resolve()
    try:
        full_path.relative_to(projects_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if full_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        raise HTTPException(status_code=403, detail="Only image files may be served")
    return FileResponse(str(full_path))


@app.get("/api/projects/{project}/sessions")
async def list_sessions(project: str):
    import config
    sessions_dir = Path(config.PROJECTS_DIR) / project / "sessions"
    if not sessions_dir.exists():
        return []
    result = []
    for f in sorted(sessions_dir.glob("session_*.json"), reverse=True):
        sid = f.stem.removeprefix("session_")
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            turns = len(data.get("turns", []))
        except Exception:
            turns = 0
        try:
            dt = datetime.strptime(sid, "%Y%m%d_%H%M%S")
            label = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            label = sid
        result.append({"id": sid, "label": label, "turns": turns})
    return result


# ── HTML ───────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Data Technician</title>
<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f1117; color: #e2e8f0; height: 100vh; display: flex;
         flex-direction: column; }

  /* Header */
  header { padding: 8px 16px; background: #1a1d27; border-bottom: 1px solid #2d3147;
           display: flex; align-items: center; gap: 10px; min-height: 44px; flex-shrink: 0; }
  header h1 { font-size: 15px; font-weight: 600; color: #a78bfa; white-space: nowrap; }
  #status-dot { width: 8px; height: 8px; border-radius: 50%; background: #6b7280; flex-shrink: 0; }
  #status-dot.connected { background: #22c55e; }
  #status-dot.thinking { background: #f59e0b; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  #status-text { font-size: 12px; color: #6b7280; margin-left: auto; white-space: nowrap; }

  /* Project / Session bar */
  .ps-bar { display: flex; align-items: center; gap: 6px; margin-left: 12px; }
  .ps-label { font-size: 10px; color: #4b5563; text-transform: uppercase; letter-spacing: 0.5px; }
  .ps-sep { color: #374151; margin: 0 4px; }
  .ps-select { background: #0f1117; border: 1px solid #2d3147; border-radius: 4px;
               color: #c4b5fd; padding: 3px 24px 3px 8px; font-size: 12px; cursor: pointer;
               appearance: none; -webkit-appearance: none;
               background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236b7280'/%3E%3C/svg%3E");
               background-repeat: no-repeat; background-position: right 6px center; }
  .ps-select:focus { outline: none; border-color: #4f46e5; }
  .ps-btn { background: #1e2235; border: 1px solid #2d3147; border-radius: 4px; color: #a78bfa;
            padding: 3px 8px; font-size: 13px; cursor: pointer; line-height: 1; }
  .ps-btn:hover { background: #2d3147; }

  .main { display: flex; flex: 1; overflow: hidden; }

  /* Chat panel */
  #chat { flex: 1; display: flex; flex-direction: column; border-right: 1px solid #2d3147; }
  #messages { flex: 1; overflow-y: auto; padding: 16px; display: flex;
              flex-direction: column; gap: 12px; }
  .msg { max-width: 85%; padding: 10px 14px; border-radius: 12px; line-height: 1.5;
         font-size: 14px; white-space: pre-wrap; word-break: break-word; }
  .msg.user { background: #4f46e5; color: #fff; align-self: flex-end; border-radius: 12px 12px 2px 12px; }
  .msg.assistant { background: #1e2235; border: 1px solid #2d3147; align-self: flex-start;
                   border-radius: 2px 12px 12px 12px; }
  .msg.assistant.streaming { white-space: normal; }  /* collapse \n to spaces while streaming */
  .msg.assistant.streaming::after { content: '▋'; animation: blink .7s infinite; color: #a78bfa; margin-left: 2px; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  .msg.assistant code { background: #0f1117; padding: 2px 6px; border-radius: 4px;
                        font-family: 'Consolas', monospace; font-size: 13px; }
  .msg.assistant pre { background: #0f1117; padding: 10px; border-radius: 6px;
                       overflow-x: auto; margin: 6px 0; }
  .msg.assistant pre code { background: none; padding: 0; }
  .msg.error { background: #450a0a; border: 1px solid #7f1d1d; color: #fca5a5; }
  .msg.info { background: #1a1d27; border: 1px solid #2d3147; color: #6b7280; font-size: 12px;
              align-self: flex-start; border-radius: 8px; }
  #input-area { padding: 12px 16px; border-top: 1px solid #2d3147; display: flex; gap: 8px; }
  #user-input { flex: 1; background: #1e2235; border: 1px solid #2d3147; border-radius: 8px;
                color: #e2e8f0; padding: 10px 14px; font-size: 14px; resize: none;
                font-family: inherit; outline: none; }
  #user-input:focus { border-color: #4f46e5; }
  #send-btn { background: #4f46e5; border: none; border-radius: 8px; color: #fff;
              padding: 10px 18px; cursor: pointer; font-size: 14px; font-weight: 500; }
  #send-btn:hover { background: #4338ca; }
  #send-btn:disabled { background: #374151; cursor: not-allowed; }

  /* Activity panel */
  #activity { width: 360px; display: flex; flex-direction: column; }
  #activity-header { padding: 10px 16px; font-size: 11px; font-weight: 600;
                     color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px;
                     border-bottom: 1px solid #2d3147; display: flex; align-items: center; gap: 8px; }
  #activity-log { flex: 1; overflow-y: auto; padding: 8px; display: flex;
                  flex-direction: column; gap: 4px; }
  .activity-item { padding: 8px 10px; border-radius: 6px; font-size: 12px;
                   font-family: 'Consolas', monospace; line-height: 1.4; }
  .activity-item.thinking-placeholder { background: #1a1d27; border-left: 3px solid #374151; color: #4b5563; }
  .activity-item.thinking-placeholder .label { color: #6b7280; animation: pulse 1.2s infinite; }
  .activity-item.tool_call { background: #1a2235; border-left: 3px solid #4f46e5; }
  .activity-item.tool_result { background: #0f2020; border-left: 3px solid #22c55e; }
  .activity-item.sub_call { background: #1a1a2e; border-left: 3px solid #7c3aed; }
  .activity-item.sub_result { background: #0e1a20; border-left: 3px solid #0ea5e9; }
  .activity-item.error { background: #1a0f0f; border-left: 3px solid #ef4444; }
  .activity-item .label { font-weight: 600; margin-bottom: 2px; }
  .activity-item.tool_call .label { color: #818cf8; }
  .activity-item.tool_result .label { color: #4ade80; }
  .activity-item.sub_call .label { color: #c084fc; }
  .activity-item.sub_result .label { color: #38bdf8; }
  .activity-item.error .label { color: #f87171; }
  .activity-item .detail { color: #94a3b8; word-break: break-all; }
  .activity-item .sub-indent { margin-left: 8px; opacity: 0.85; }
  #clear-btn { margin: 8px; padding: 6px; background: none; border: 1px solid #2d3147;
               border-radius: 4px; color: #6b7280; cursor: pointer; font-size: 11px; }
  #clear-btn:hover { color: #e2e8f0; }

  /* Plot images in activity log */
  .activity-item .plot-img { display: block; max-width: 100%; border-radius: 4px;
                              margin-top: 6px; cursor: zoom-in; border: 1px solid #2d3147; }
  .activity-item .plot-img:hover { border-color: #4f46e5; }

  /* Plot images in main chat */
  .msg.assistant .plot-img { display: block; max-width: 100%; border-radius: 6px;
                              cursor: zoom-in; border: 1px solid #2d3147; }
  .msg.assistant .plot-img:hover { border-color: #4f46e5; }

  /* Lightbox */
  #lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.92);
              z-index: 1000; align-items: center; justify-content: center; cursor: zoom-out; }
  #lightbox.open { display: flex; }
  #lightbox img { max-width: 92vw; max-height: 92vh; border-radius: 6px;
                  box-shadow: 0 0 40px rgba(0,0,0,.8); }

  /* Generic plot modal — interactive Plotly popup */
  #plot-modal { display: none; position: fixed; inset: 0; z-index: 940;
                background: rgba(0,0,0,.92); align-items: center; justify-content: center;
                padding: 16px; }
  #plot-modal.open { display: flex; }
  #plot-modal-card { background: #1a1d27; border: 1px solid #2d3147; border-radius: 12px;
                     padding: 16px; width: 96vw; height: 94vh;
                     display: flex; flex-direction: column; gap: 10px; overflow: hidden; }
  #plot-modal-header { display: flex; justify-content: space-between; align-items: center;
                       flex-shrink: 0; }
  #plot-modal-title { font-size: 13px; font-weight: 600; color: #c4b5fd; }
  #plot-modal-close { background: none; border: none; color: #6b7280; cursor: pointer;
                      font-size: 18px; line-height: 1; padding: 2px 6px; border-radius: 4px; }
  #plot-modal-close:hover { color: #e2e8f0; background: #2d3147; }
  #plot-modal-chart { width: 100%; flex: 1; min-height: 0; }
  /* Feedback bar — shown inside the modal when agent asks a question */
  #plot-modal-feedback { display: none; flex-shrink: 0; background: #111827;
                         border-top: 1px solid #2d3147; border-radius: 0 0 8px 8px;
                         padding: 10px 14px; gap: 8px; flex-direction: column; }
  #plot-modal-feedback.visible { display: flex; }
  #plot-modal-question { font-size: 13px; color: #e2e8f0; line-height: 1.4; }
  #plot-modal-quick-btns { display: flex; gap: 8px; flex-wrap: wrap; }
  #plot-modal-quick-btns button { background: #1f2937; border: 1px solid #374151; color: #d1d5db;
                                   font-size: 12px; padding: 4px 12px; border-radius: 6px;
                                   cursor: pointer; }
  #plot-modal-quick-btns button:hover { background: #374151; color: #f9fafb; }
  #plot-modal-quick-btns button.primary { background: #4f46e5; border-color: #6366f1; color: #fff; }
  #plot-modal-input-row { display: flex; gap: 8px; }
  #plot-modal-input { flex: 1; background: #1f2937; border: 1px solid #374151; color: #e2e8f0;
                      font-size: 13px; padding: 6px 10px; border-radius: 6px; outline: none; }
  #plot-modal-input:focus { border-color: #6366f1; }
  #plot-modal-send { background: #4f46e5; border: none; color: #fff; font-size: 13px;
                     padding: 6px 16px; border-radius: 6px; cursor: pointer; }
  #plot-modal-send:hover { background: #6366f1; }

  /* Plot-modal two-column body: chart | divider | labeling panel */
  #plot-modal-body { display: flex; flex: 1; min-height: 0; gap: 0; overflow: hidden; }
  #plot-modal-chart { flex: 1; min-width: 200px; min-height: 0; }
  #pm-divider { width: 5px; flex-shrink: 0; cursor: col-resize; background: #2d3147;
                transition: background .15s; user-select: none; }
  #pm-divider:hover, #pm-divider.dragging { background: #6366f1; }
  #pm-panel { width: 300px; flex-shrink: 0; background: #111827; border-left: 1px solid #2d3147;
              display: flex; flex-direction: column; overflow-y: auto; padding: 10px 12px; gap: 6px; }
  .pm-section-lbl { font-size: 11px; font-weight: 700; color: #f59e0b; letter-spacing: .05em;
                    text-transform: uppercase; margin-top: 4px; }
  .pm-small { font-size: 11px; color: #6b7280; }
  #pm-sel-list { font-size: 11px; font-family: monospace; color: #94a3b8; min-height: 20px;
                 max-height: 90px; overflow-y: auto; white-space: pre; }
  #pm-sel-count { font-size: 11px; color: #6b7280; font-style: italic; }
  .pm-hr { border: none; border-top: 1px solid #1f2937; margin: 6px 0; }
  #pm-patterns-list { display: flex; flex-direction: column; gap: 3px; max-height: 160px; overflow-y: auto; }
  .pm-pat-row { display: flex; align-items: center; gap: 6px; }
  .pm-pat-row input[type=checkbox] { accent-color: #22c55e; cursor: pointer; }
  .pm-pat-row label { font-size: 12px; color: #22c55e; cursor: pointer; }
  .pm-input { width: 100%; box-sizing: border-box; background: #1f2937; border: 1px solid #374151;
              color: #e2e8f0; font-size: 12px; padding: 5px 8px; border-radius: 5px;
              outline: none; font-family: monospace; }
  .pm-input:focus { border-color: #6366f1; }
  .pm-textarea { resize: vertical; min-height: 40px; }
  #pm-cat-btns { display: flex; gap: 6px; }
  .pm-cat-btn { flex: 1; padding: 5px 0; border: 2px solid transparent; border-radius: 5px;
                font-size: 12px; font-weight: 600; cursor: pointer; background: #1f2937; color: #9ca3af; }
  .pm-cat-btn[data-cat=reject].active { background: #7f1d1d; border-color: #ef4444; color: #fca5a5; }
  .pm-cat-btn[data-cat=accept].active { background: #14532d; border-color: #22c55e; color: #86efac; }
  .pm-cat-btn:hover { background: #374151; }
  #pm-action-btns { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
  .pm-btn-submit { background: #3b82f6; border: none; color: #fff; font-size: 13px; font-weight: 700;
                   padding: 8px; border-radius: 6px; cursor: pointer; }
  .pm-btn-submit:hover { background: #2563eb; }
  .pm-btn-clear  { background: #1f2937; border: 1px solid #374151; color: #9ca3af; font-size: 11px;
                   padding: 4px 8px; border-radius: 5px; cursor: pointer; }
  .pm-btn-clear:hover { background: #374151; }
  .pm-btn-danger { background: #7f1d1d; border: 1px solid #ef4444; color: #fca5a5; font-size: 12px;
                   font-weight: 700; padding: 6px; border-radius: 5px; cursor: pointer; }
  .pm-btn-danger:hover { background: #dc2626; color: #fff; }

  /* Label modal — interactive signal labelling popup */
  #label-modal { display: none; position: fixed; inset: 0; z-index: 950;
                 background: rgba(0,0,0,.92); align-items: center; justify-content: center;
                 padding: 16px; }
  #label-modal.open { display: flex; }
  #label-modal-card { background: #1a1d27; border: 1px solid #2d3147; border-radius: 12px;
                      padding: 16px; width: 96vw; height: 94vh;
                      display: flex; flex-direction: column; gap: 10px; overflow: hidden; }
  #label-modal-header { display: flex; justify-content: space-between;
                        font-size: 12px; color: #6b7280; font-family: 'Consolas', monospace;
                        flex-shrink: 0; }
  #label-modal-btns { display: flex; gap: 10px; flex-wrap: wrap; flex-shrink: 0; }
  #label-modal-plot { width: 100%; flex: 1; min-height: 0; }
  #label-modal-context { font-size: 12px; color: #94a3b8; flex-shrink: 0; }
  .lbl-btn { padding: 10px 22px; border: none; border-radius: 6px; cursor: pointer;
             font-size: 14px; font-weight: 600; transition: transform .1s, box-shadow .1s; }
  .lbl-btn:hover { transform: scale(1.04); box-shadow: 0 0 10px rgba(0,0,0,.4); }
  .lbl-btn:active { transform: scale(.97); }

  /* Markdown rendering */
  .msg.assistant h1,.msg.assistant h2,.msg.assistant h3 {
    margin: 8px 0 4px; font-size: 1em; }
  .msg.assistant ul,.msg.assistant ol { padding-left: 20px; margin: 4px 0; }
  .msg.assistant table { border-collapse: collapse; margin: 8px 0; width: 100%; font-size: 12px; }
  .msg.assistant th,.msg.assistant td { border: 1px solid #2d3147; padding: 4px 8px; }
  .msg.assistant th { background: #1a1d27; }
  .msg.assistant hr { border-color: #2d3147; margin: 8px 0; }
  .msg.assistant strong { color: #c4b5fd; }
</style>
</head>
<body>
<header>
  <div id="status-dot"></div>
  <h1>AI Data Technician</h1>
  <div class="ps-bar">
    <span class="ps-label">Project</span>
    <select id="project-select" class="ps-select"></select>
    <button class="ps-btn" id="new-project-btn" title="New project">+</button>
    <span class="ps-sep">·</span>
    <span class="ps-label">Session</span>
    <select id="session-select" class="ps-select"></select>
  </div>
  <span id="status-text">Connecting...</span>
</header>
<div class="main">
  <div id="chat">
    <div id="messages">
      <div class="msg assistant">Hello! I'm your AI Data Technician. Share a dataset path to get started, or ask me anything about EEG/neural signal analysis.</div>
    </div>
    <div id="input-area">
      <textarea id="user-input" rows="2" placeholder="Type a message... (Enter to send, Shift+Enter for newline)"></textarea>
      <button id="send-btn">Send</button>
    </div>
  </div>
  <div id="activity">
    <div id="activity-header">
      <span>Activity Log</span>
    </div>
    <div id="activity-log"></div>
    <button id="clear-btn" onclick="document.getElementById('activity-log').innerHTML=''">Clear log</button>
  </div>
</div>

<div id="lightbox" onclick="closeLightbox()">
  <img id="lightbox-img" src="" alt="">
</div>

<div id="plot-modal">
  <div id="plot-modal-card">
    <div id="plot-modal-header">
      <span id="plot-modal-title"></span>
      <div style="display:flex;gap:8px;align-items:center">
        <span id="pm-trial-status" style="font-size:11px;color:#6b7280;font-family:monospace"></span>
        <button id="plot-modal-close" onclick="closePlotModal()">✕</button>
      </div>
    </div>
    <div id="plot-modal-body">
      <div id="plot-modal-chart"></div>
      <div id="pm-divider" title="Drag to resize"></div>
      <!-- Right labeling panel (mirrors trial_view_gui side panel) -->
      <div id="pm-panel">
        <div class="pm-section-lbl">Selected Channels</div>
        <div id="pm-sel-list"></div>
        <div id="pm-sel-count">Click a trace to select</div>
        <button class="pm-btn-clear" onclick="pmClearSelection()">Clear Selection</button>
        <hr class="pm-hr">
        <div class="pm-section-lbl">Patterns</div>
        <div id="pm-patterns-list"></div>
        <div class="pm-small" style="margin-top:4px">New (;-sep):</div>
        <input id="pm-new-pat" class="pm-input" type="text" placeholder="spike; artifact">
        <hr class="pm-hr">
        <div class="pm-section-lbl">Category</div>
        <div id="pm-cat-btns">
          <button class="pm-cat-btn active" data-cat="reject" onclick="pmSetCategory('reject')">Reject</button>
          <button class="pm-cat-btn" data-cat="accept" onclick="pmSetCategory('accept')">Accept</button>
        </div>
        <hr class="pm-hr">
        <div class="pm-small">Description (optional):</div>
        <textarea id="pm-desc" class="pm-input pm-textarea"></textarea>
        <div id="pm-action-btns">
          <button class="pm-btn-submit" onclick="pmSubmit()">Submit</button>
          <button class="pm-btn-danger" onclick="pmMarkAllBad()">Mark ALL Bad (X)</button>
        </div>
      </div>
    </div>
    <!-- Feedback bar for ask_user questions -->
    <div id="plot-modal-feedback">
      <div id="plot-modal-question"></div>
      <div id="plot-modal-quick-btns">
        <button class="primary" onclick="submitPlotFeedback('yes')">✓ Looks good — start labelling</button>
        <button onclick="submitPlotFeedback('default')">Use default view</button>
      </div>
      <div id="plot-modal-input-row">
        <input id="plot-modal-input" type="text" placeholder="Or describe a change and press Enter…"
               onkeydown="if(event.key==='Enter') submitPlotFeedback()">
        <button id="plot-modal-send" onclick="submitPlotFeedback()">Send</button>
      </div>
    </div>
  </div>
</div>

<div id="label-modal">
  <div id="label-modal-card">
    <div id="label-modal-header">
      <span id="label-modal-progress"></span>
      <span id="label-modal-id"></span>
    </div>
    <div id="label-modal-context"></div>
    <div id="label-modal-btns"></div>
    <div id="label-modal-plot"></div>
  </div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let ws;
let thinking = false;
let waitingForAnswer = false;  // true when agent has called ask_user
let pendingMsg = null;
let pendingText = '';   // accumulates raw markdown during streaming
let thinkingEntry = null;
let currentProject = 'default';
let currentSessionId = 'new';

// ── Image helpers ──────────────────────────────────────────────────────────────
function imgUrl(absPath) {
  return '/files?path=' + encodeURIComponent(absPath);
}

function openLightbox(src) {
  document.getElementById('lightbox-img').src = src;
  document.getElementById('lightbox').classList.add('open');
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lightbox-img').src = '';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeLightbox(); closePlotModal(); } });

function plotImgHtml(absPath) {
  const url = imgUrl(absPath);
  return `<img class="plot-img" src="${url}" alt="plot" onclick="event.stopPropagation();openLightbox('${url}')">`;
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    // Send project/session selection as first message
    ws.send(JSON.stringify({type: 'init', project: currentProject, session_id: currentSessionId}));
    setStatus('thinking', 'Connecting...');
  };
  ws.onclose = () => {
    setStatus('', 'Disconnected — reconnecting...');
    setTimeout(connect, 2000);
  };
  ws.onerror = () => {};
  ws.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      handleEvent(ev);
    } catch(err) {
      console.error('ws.onmessage error:', err, e.data);
    }
  };
}

function setStatus(cls, text) {
  const dot = document.getElementById('status-dot');
  dot.className = cls;
  document.getElementById('status-text').textContent = text;
}

// ── Project / Session management ──────────────────────────────────────────────
async function loadProjects() {
  const resp = await fetch('/api/projects');
  if (!resp.ok) throw new Error(`/api/projects returned ${resp.status}`);
  const projects = await resp.json();
  const sel = document.getElementById('project-select');
  sel.innerHTML = '';
  const list = projects.length ? projects : [currentProject];
  for (const p of list) {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    if (p === currentProject) opt.selected = true;
    sel.appendChild(opt);
  }
  if (!list.includes(currentProject)) {
    currentProject = list[0];
    sel.value = currentProject;
  }
}

async function loadSessions(selectId) {
  const resp = await fetch(`/api/projects/${encodeURIComponent(currentProject)}/sessions`);
  if (!resp.ok) throw new Error(`sessions api returned ${resp.status}`);
  const sessions = await resp.json();
  const sel = document.getElementById('session-select');
  sel.innerHTML = '<option value="new">+ New Session</option>';
  for (const s of sessions) {
    const opt = document.createElement('option');
    opt.value = s.id;
    const n = Math.floor(s.turns / 2);
    opt.textContent = s.label + (n > 0 ? ` (${n} msg)` : ' (empty)');
    if (s.id === selectId) opt.selected = true;
    sel.appendChild(opt);
  }
  if (!selectId || selectId === 'new') sel.value = 'new';
}

function clearAndReconnect() {
  clearChat();
  clearActivity();
  if (ws) { ws.onclose = null; ws.close(); }
  connect();
}

function clearChat() {
  document.getElementById('messages').innerHTML =
    "<div class='msg assistant'>Hello! I'm your AI Data Technician. Share a dataset path to get started, or ask me anything about EEG/neural signal analysis.</div>";
  pendingMsg = null;
  pendingText = '';
  thinkingEntry = null;
  thinking = false;
  waitingForAnswer = false;
  document.getElementById('user-input').placeholder = 'Type a message... (Enter to send, Shift+Enter for newline)';
  document.getElementById('send-btn').disabled = false;
}

function clearActivity() {
  document.getElementById('activity-log').innerHTML = '';
}

document.getElementById('project-select').addEventListener('change', async function() {
  if (this.value === currentProject) return;
  currentProject = this.value;
  currentSessionId = 'new';
  await loadSessions();
  clearAndReconnect();
});

document.getElementById('session-select').addEventListener('change', function() {
  const val = this.value;
  if (val === currentSessionId) return;
  currentSessionId = val;
  clearAndReconnect();
});

document.getElementById('new-project-btn').addEventListener('click', async function() {
  const name = prompt('New project name:');
  if (!name || !name.trim()) return;
  try {
    const resp = await fetch(`/api/projects/${encodeURIComponent(name.trim())}`, {method: 'POST'});
    const data = await resp.json();
    currentProject = data.name;
    currentSessionId = 'new';
    await loadProjects();
    document.getElementById('project-select').value = currentProject;
    await loadSessions();
    clearAndReconnect();
  } catch(e) {
    console.error('Failed to create project:', e);
    alert('Failed to create project. See console for details.');
  }
});

// ── Event handling ─────────────────────────────────────────────────────────────
function handleEvent(ev) {
  if (ev.type === 'session_info') {
    currentSessionId = ev.session_id;
    if (ev.project) currentProject = ev.project;
    // Set ready immediately — don't block on async session list reload
    setStatus('connected', 'Ready');
    if (ev.turns > 0) {
      const n = Math.floor(ev.turns / 2);
      appendMessage('info', `Continuing session from ${ev.label} (${n} message exchange${n !== 1 ? 's' : ''}).`);
    }
    // Reload session dropdown in background
    loadSessions(ev.session_id).catch(e => console.warn('loadSessions:', e));
    return;
  }

  if (ev.type === 'text_delta') {
    clearThinkingEntry();
    pendingText += ev.delta;
    if (!pendingMsg) {
      pendingMsg = document.createElement('div');
      pendingMsg.className = 'msg assistant streaming';
      document.getElementById('messages').appendChild(pendingMsg);
    }
    pendingMsg.textContent = pendingText;  // raw during streaming; renderMarkdown runs on response
    document.getElementById('messages').scrollTop = 99999;

  } else if (ev.type === 'tool_call') {
    clearThinkingEntry();
    const imgP = ev.tool === 'vision_analyze' ? (ev.input && ev.input.image_path) : null;
    logActivity('tool_call', ev.tool, formatInput(ev.tool, ev.input), imgP);
    setStatus('thinking', `Running ${ev.tool}...`);
    // Also show analyzed image inline in the main chat
    if (imgP) {
      const imgDiv = document.createElement('div');
      imgDiv.className = 'msg assistant';
      imgDiv.innerHTML = plotImgHtml(imgP);
      document.getElementById('messages').appendChild(imgDiv);
      document.getElementById('messages').scrollTop = 99999;
    }

  } else if (ev.type === 'tool_result') {
    logActivity('tool_result', ev.tool, formatResult(ev.tool, ev.result || ''));

  } else if (ev.type === 'sub_tool_call') {
    // Intermediate step inside a subagent (e.g. explore's bash calls)
    const imgP2 = ev.tool === 'vision_analyze' ? (ev.input && ev.input.image_path) : null;
    logSubActivity('sub_call', ev.subagent, ev.tool, formatInput(ev.tool, ev.input), imgP2);
    if (imgP2) {
      const imgDiv = document.createElement('div');
      imgDiv.className = 'msg assistant';
      imgDiv.innerHTML = plotImgHtml(imgP2);
      document.getElementById('messages').appendChild(imgDiv);
      document.getElementById('messages').scrollTop = 99999;
    }

  } else if (ev.type === 'sub_tool_result') {
    logSubActivity('sub_result', ev.subagent, ev.tool, formatResult(ev.tool, ev.result || ''));

  } else if (ev.type === 'response') {
    clearThinkingEntry();
    if (pendingMsg) { pendingMsg.remove(); pendingMsg = null; }
    pendingText = '';
    appendMessage('assistant', ev.content);
    setStatus('connected', 'Ready');
    thinking = false;
    document.getElementById('send-btn').disabled = false;

  } else if (ev.type === 'error') {
    clearThinkingEntry();
    if (pendingMsg) { pendingMsg.remove(); pendingMsg = null; }
    pendingText = '';
    appendMessage('error', ev.message);
    setStatus('connected', 'Ready');
    thinking = false;
    document.getElementById('send-btn').disabled = false;

  } else if (ev.type === 'thinking') {
    setStatus('thinking', 'Thinking...');
    if (!thinkingEntry) {
      thinkingEntry = document.createElement('div');
      thinkingEntry.className = 'activity-item thinking-placeholder';
      thinkingEntry.innerHTML = '<div class="label">⟳ Deciding what to do...</div>';
      document.getElementById('activity-log').appendChild(thinkingEntry);
      document.getElementById('activity-log').scrollTop = 99999;
    }

  } else if (ev.type === 'labels_saved') {
    // Server confirmed label save — update local state with authoritative sets
    pmState.rejectedChannels = new Set(ev.rejected || []);
    pmState.acceptedChannels = new Set(ev.accepted || []);
    pmRestyleSelected();
    pmUpdateSelectionDisplay();

  } else if (ev.type === 'show_plot') {
    clearThinkingEntry();
    showPlotModal(ev);

  } else if (ev.type === 'label_signal') {
    clearThinkingEntry();
    showLabelModal(ev);

  } else if (ev.type === 'ask_user') {
    clearThinkingEntry();
    waitingForAnswer = true;
    thinking = false;
    const modalOpen = document.getElementById('plot-modal').classList.contains('open');
    if (modalOpen) {
      // Modal already open — show feedback bar immediately
      document.getElementById('plot-modal-question').textContent = ev.question;
      document.getElementById('plot-modal-feedback').classList.add('visible');
      document.getElementById('plot-modal-input').focus();
    } else if (pmPendingQuestion !== null || document.getElementById('plot-modal-chart').data !== undefined) {
      // show_plot was just sent — buffer the question for when the modal opens
      pmPendingQuestion = ev.question;
    } else {
      // No plot modal involved — show in main chat
      appendMessage('assistant', ev.question);
      document.getElementById('send-btn').disabled = false;
      document.getElementById('user-input').placeholder = 'Type your answer and press Enter...';
      setStatus('thinking', 'Waiting for your answer...');
    }
  }
}

function clearThinkingEntry() {
  if (thinkingEntry) { thinkingEntry.remove(); thinkingEntry = null; }
}

// ── Plot-modal labeling state ────────────────────────────────────────────────
let pmState = {
  trialIdx: null, project: null,
  chTraceMap: {},        // ch_idx (int) -> trace index in fig.data
  traceRevMap: {},       // trace_idx (int) -> ch_idx (reverse lookup)
  traceOrigColors: {},   // trace_idx -> original hex color
  traceOrigWidths: {},   // trace_idx -> original line.width
  traceOrigOpacity: {},  // trace_idx -> original opacity
  selectedChannels: new Set(),
  rejectedChannels: new Set(),
  acceptedChannels: new Set(),
  category: 'reject',
};
// Pending ask_user question to show when modal finishes opening
let pmPendingQuestion = null;

function showPlotModal(ev) {
  document.getElementById('plot-modal-title').textContent = ev.title || 'Plot';
  const fig = JSON.parse(ev.plot_json);

  // Reset state
  pmState.chTraceMap = {};
  pmState.traceRevMap = {};
  pmState.traceOrigColors = {};
  pmState.traceOrigWidths = {};
  pmState.traceOrigOpacity = {};
  pmState.selectedChannels = new Set();
  pmState.rejectedChannels = new Set();
  pmState.acceptedChannels = new Set();
  pmState.category = 'reject';
  pmState.trialIdx = ev.trial_idx !== undefined ? ev.trial_idx : null;
  pmState.project = currentProject;

  // Strip layout artifacts that waste space when panel is present
  if (fig.layout) {
    fig.layout.showlegend = false;
    // Remove the large right margin used for standalone channel-label annotations
    if (fig.layout.margin) fig.layout.margin.r = 8;
    else fig.layout.margin = {l: 60, r: 8, t: 50, b: 50};
    // Remove right-side channel label annotations (x≥0.95, xanchor=left, xref=paper)
    if (fig.layout.annotations) {
      fig.layout.annotations = fig.layout.annotations.filter(a =>
        !(a.xref === 'paper' && a.xanchor === 'left' && a.x >= 0.95));
    }
    // Box-select as default drag (drag a vertical band to multi-select traces)
    fig.layout.dragmode = 'select';
    fig.layout.selectdirection = 'any';
  }

  // Build ch->trace map from customdata ([ch_idx, region, ch_name, trial_idx])
  fig.data.forEach((trace, i) => {
    if (trace.customdata && trace.customdata.length > 0) {
      const cd = Array.isArray(trace.customdata[0]) ? trace.customdata[0] : trace.customdata;
      const chCandidate = Array.isArray(cd) ? cd[0] : null;
      if (chCandidate !== null && typeof chCandidate === 'number') {
        pmState.chTraceMap[chCandidate] = i;
        pmState.traceRevMap[i] = chCandidate;
        pmState.traceOrigColors[i] = (trace.line && trace.line.color) ? trace.line.color : '#888888';
        pmState.traceOrigWidths[i] = (trace.line && trace.line.width) ? trace.line.width : 0.6;
        pmState.traceOrigOpacity[i] = trace.opacity !== undefined ? trace.opacity : 1.0;
      }
    }
  });

  pmSetCategory('reject');
  pmLoadPatterns();
  pmUpdateSelectionDisplay();
  document.getElementById('pm-trial-status').textContent = '';

  Plotly.newPlot('plot-modal-chart', fig.data, fig.layout, {
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToRemove: ['lasso2d'],
    toImageButtonOptions: {format: 'png', filename: (ev.title || 'plot').replace(/\s+/g, '_')},
  });
  pmBindEvents();

  document.getElementById('plot-modal').classList.add('open');

  // Show any buffered ask_user question
  if (pmPendingQuestion) {
    const fb = document.getElementById('plot-modal-feedback');
    document.getElementById('plot-modal-question').textContent = pmPendingQuestion;
    fb.classList.add('visible');
    pmPendingQuestion = null;
  }
}

function closePlotModal() {
  document.getElementById('plot-modal').classList.remove('open');
  document.getElementById('plot-modal-feedback').classList.remove('visible');
  document.getElementById('plot-modal-input').value = '';
  pmPendingQuestion = null;
  Plotly.purge('plot-modal-chart');
}

function submitPlotFeedback(fixedValue) {
  const val = fixedValue !== undefined
    ? fixedValue
    : document.getElementById('plot-modal-input').value.trim();
  if (!val) return;
  document.getElementById('plot-modal-feedback').classList.remove('visible');
  document.getElementById('plot-modal-input').value = '';
  closePlotModal();
  waitingForAnswer = false;
  ws.send(JSON.stringify({ type: 'user_answer', content: val }));
  appendMessage('user', val);
  thinking = true;
  document.getElementById('send-btn').disabled = true;
  document.getElementById('user-input').placeholder = 'Ask anything about the data…';
  setStatus('thinking', 'Agent is working…');
}

document.getElementById('plot-modal').addEventListener('click', function(e) {
  if (e.target === this) closePlotModal();
});

// ── Plot-modal event binding (re-called after every Plotly.react) ────────────

function pmBindEvents() {
  const d = document.getElementById('plot-modal-chart');
  if (!d) return;
  // Plotly uses a custom EventEmitter; removeAllListeners clears previous bindings
  ['plotly_click','plotly_selected','plotly_deselect'].forEach(ev => {
    try { d.removeAllListeners(ev); } catch(e) {}
  });
  d.on('plotly_click',    pmHandleClick);
  d.on('plotly_selected', pmHandleSelected);
  d.on('plotly_deselect', pmHandleDeselect);
}

function pmHandleSelected(eventData) {
  // Box-select: all traces whose points were inside the selection box
  if (!eventData || !eventData.points) return;
  const curves = new Set(eventData.points.map(p => p.curveNumber));
  curves.forEach(curveNum => {
    const ch = pmState.traceRevMap[curveNum];
    if (ch !== undefined) pmState.selectedChannels.add(ch);
  });
  pmRestyleSelected();
  pmUpdateSelectionDisplay();
}

function pmHandleDeselect() {
  pmState.selectedChannels.clear();
  pmRestyleSelected();
  pmUpdateSelectionDisplay();
}

// ── Plot-modal labeling panel functions ──────────────────────────────────────

async function pmLoadPatterns() {
  if (!pmState.project) return;
  try {
    const resp = await fetch(`/api/projects/${pmState.project}/patterns`);
    const patterns = await resp.json();
    const list = document.getElementById('pm-patterns-list');
    list.innerHTML = '';
    patterns.forEach(pat => {
      const row = document.createElement('div');
      row.className = 'pm-pat-row';
      const label = pat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      row.innerHTML = `<input type="checkbox" data-pat="${pat}" id="pmpat_${pat}">
                       <label for="pmpat_${pat}">${label}</label>`;
      list.appendChild(row);
    });
  } catch(e) { console.warn('Could not load patterns:', e); }
}

function pmSetCategory(cat) {
  pmState.category = cat;
  document.querySelectorAll('.pm-cat-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cat === cat);
  });
}

function pmHandleClick(data) {
  if (!data.points || data.points.length === 0) return;
  const pt = data.points[0];

  // Primary: curveNumber → reverse map to ch_idx
  let chIdx = pmState.traceRevMap[pt.curveNumber];

  // Fallback: customdata
  if (chIdx === undefined && pt.customdata) {
    const cd = pt.customdata;
    const first = Array.isArray(cd) ? (Array.isArray(cd[0]) ? cd[0][0] : cd[0]) : cd;
    if (typeof first === 'number') chIdx = first;
  }

  if (chIdx === undefined || chIdx === null) return;

  if (pmState.selectedChannels.has(chIdx)) {
    pmState.selectedChannels.delete(chIdx);
  } else {
    pmState.selectedChannels.add(chIdx);
  }
  pmRestyleSelected();
  pmUpdateSelectionDisplay();
}

function pmRestyleSelected() {
  const chartDiv = document.getElementById('plot-modal-chart');
  if (!chartDiv.data || !chartDiv.data.length) return;

  // Clone figure data and update only channel traces; use Plotly.react for reliability
  const newData = chartDiv.data.map((trace, i) => {
    const ch = pmState.traceRevMap[i];
    if (ch === undefined) return trace; // legend dummy or non-channel trace

    let color, width, opacity;
    if (pmState.selectedChannels.has(ch)) {
      color = '#ffffff'; width = 2.5; opacity = 1.0;
    } else if (pmState.rejectedChannels.has(ch)) {
      color = '#ef4444'; width = 1.0; opacity = 1.0;
    } else if (pmState.acceptedChannels.has(ch)) {
      color = '#3a3a3a'; width = 0.4; opacity = 0.4;
    } else {
      color = pmState.traceOrigColors[i] || '#888888';
      width = pmState.traceOrigWidths[i] || 0.6;
      opacity = pmState.traceOrigOpacity[i] !== undefined ? pmState.traceOrigOpacity[i] : 1.0;
    }
    return {...trace, line: {...(trace.line || {}), color, width}, opacity};
  });

  Plotly.react('plot-modal-chart', newData, chartDiv.layout);
  // Plotly.react can detach event listeners — re-bind immediately
  pmBindEvents();
}

function pmUpdateSelectionDisplay() {
  const list = document.getElementById('pm-sel-list');
  const count = document.getElementById('pm-sel-count');
  const n = pmState.selectedChannels.size;
  if (n === 0) {
    list.textContent = '';
    count.textContent = 'Click a trace to select';
  } else {
    list.textContent = Array.from(pmState.selectedChannels).sort((a,b)=>a-b)
      .map(ch => `ch${String(ch).padStart(2,'0')}`).join('  ');
    count.textContent = `${n} channel${n>1?'s':''} selected`;
  }
  // Update trial status (rej/acc/unlabeled)
  const nRej = pmState.rejectedChannels.size;
  const nAcc = pmState.acceptedChannels.size;
  document.getElementById('pm-trial-status').textContent =
    nRej + nAcc > 0 ? `${nRej} bad / ${nAcc} ok` : '';
}

function pmClearSelection() {
  pmState.selectedChannels.clear();
  pmRestyleSelected();
  pmUpdateSelectionDisplay();
}

function pmSubmit() {
  if (pmState.selectedChannels.size === 0) {
    alert('Click traces on the chart to select channels first.'); return;
  }
  const newPatRaw = document.getElementById('pm-new-pat').value.trim();
  let patterns = Array.from(document.querySelectorAll('#pm-patterns-list input:checked'))
    .map(cb => cb.dataset.pat);
  if (newPatRaw) {
    newPatRaw.replace(/,/g, ';').split(';').forEach(t => {
      const p = t.trim().toLowerCase().replace(/\s+/g, '_').replace(/-/g, '_');
      if (p) patterns.push(p);
    });
  }
  if (patterns.length === 0 && pmState.category !== 'accept') {
    alert('Select at least one pattern, or switch category to Accept.'); return;
  }
  if (patterns.length === 0) patterns = ['physiology'];
  const desc = document.getElementById('pm-desc').value.trim();
  const channels = Array.from(pmState.selectedChannels);
  ws.send(JSON.stringify({
    type: 'label_channels',
    trial_idx: pmState.trialIdx,
    channels, patterns,
    category: pmState.category,
    description: desc,
  }));
  // Optimistic local update
  channels.forEach(ch => {
    if (pmState.category === 'reject') {
      pmState.rejectedChannels.add(ch); pmState.acceptedChannels.delete(ch);
    } else {
      pmState.acceptedChannels.add(ch); pmState.rejectedChannels.delete(ch);
    }
  });
  pmState.selectedChannels.clear();
  // Add new patterns to panel
  if (newPatRaw) pmLoadPatterns();
  document.getElementById('pm-new-pat').value = '';
  document.getElementById('pm-desc').value = '';
  document.querySelectorAll('#pm-patterns-list input').forEach(cb => cb.checked = false);
  pmRestyleSelected();
  pmUpdateSelectionDisplay();
}

function pmMarkAllBad() {
  if (!confirm('Mark ALL channels in this trial as bad?')) return;
  const channels = Object.keys(pmState.chTraceMap).map(Number);
  ws.send(JSON.stringify({
    type: 'label_channels',
    trial_idx: pmState.trialIdx,
    channels,
    patterns: ['trial_wide_artifact'],
    category: 'reject',
    description: 'Marked all channels bad for this trial',
  }));
  channels.forEach(ch => {
    pmState.rejectedChannels.add(ch); pmState.acceptedChannels.delete(ch);
  });
  pmState.selectedChannels.clear();
  pmRestyleSelected();
  pmUpdateSelectionDisplay();
}

function showLabelModal(ev) {
  document.getElementById('label-modal-progress').textContent = ev.progress || '';
  document.getElementById('label-modal-id').textContent = ev.signal_id || '';
  document.getElementById('label-modal-context').textContent = ev.context_text || '';

  // Render interactive Plotly chart
  const fig = JSON.parse(ev.plot_json);
  Plotly.newPlot('label-modal-plot', fig.data, fig.layout, {
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
    toImageButtonOptions: {format: 'png', filename: ev.signal_id || 'signal'},
  });

  const palette = {
    clean: {bg: '#22c55e', fg: '#000'},
    artifact: {bg: '#ef4444', fg: '#fff'},
    noise: {bg: '#f59e0b', fg: '#000'},
    unsure: {bg: '#6366f1', fg: '#fff'},
    skip: {bg: '#374151', fg: '#9ca3af'},
  };
  const btns = document.getElementById('label-modal-btns');
  btns.innerHTML = '';
  const options = ev.options || ['clean', 'artifact', 'noise', 'unsure', 'skip'];
  for (const opt of options) {
    const c = palette[opt] || {bg: '#4f46e5', fg: '#fff'};
    const btn = document.createElement('button');
    btn.className = 'lbl-btn';
    btn.style.background = c.bg;
    btn.style.color = c.fg;
    btn.textContent = opt.charAt(0).toUpperCase() + opt.slice(1);
    btn.onclick = () => {
      document.getElementById('label-modal').classList.remove('open');
      appendMessage('user', opt);
      ws.send(JSON.stringify({type: 'user_answer', content: opt}));
    };
    btns.appendChild(btn);
  }
  document.getElementById('label-modal').classList.add('open');
}

// ── Formatting helpers ─────────────────────────────────────────────────────────
function formatInput(tool, inp) {
  if (!inp) return '';
  if (tool === 'todo_write') {
    const todos = inp.todos || [];
    return todos.map(t => {
      const icon = t.status === 'done' ? '✓' : t.status === 'running' ? '▶' : t.status === 'failed' ? '✗' : '○';
      return `${icon} ${t.title || t.id}`;
    }).join('\\n') || '(empty list)';
  }
  if (tool === 'bash' || tool === 'bash_execute') return inp.command || '';
  if (tool === 'explore_dataset') return inp.data_dir || '';
  if (tool === 'explore') return (inp.task || '') + (inp.data_dir ? `\\n@ ${inp.data_dir}` : '');
  if (tool === 'statistics') return inp.task || '';
  if (tool === 'ask_user') return inp.question || '';
  if (tool === 'vision_analyze') return (inp.image_path || '').split(/[\\/]/).pop();
  if (tool === 'optimize_pattern' || tool === 'teach_session' || tool === 'review_results' || tool === 'apply_rules')
    return inp.pattern ? `pattern: ${inp.pattern}` : '';
  if (tool === 'ingest_documents') {
    const files = inp.file_paths || [];
    return files.length ? files.map(f => f.split(/[\\/]/).pop()).join(', ') : inp.data_dir || '';
  }
  return Object.entries(inp).map(([k,v]) => {
    const s = String(v);
    return `${k}: ${s.length > 60 ? s.slice(0,57)+'...' : s}`;
  }).join('\\n');
}

function formatResult(tool, result) {
  if (!result) return '';
  let parsed = null;
  try { parsed = JSON.parse(result); } catch(e) {}
  if (tool === 'todo_write') {
    if (parsed && parsed.error) return '✗ ' + parsed.error.slice(0, 120);
    if (parsed && parsed.todos_saved) return `Saved ${parsed.count} todos`;
    return result.slice(0, 100);
  }
  if (tool === 'bash' || tool === 'bash_execute') {
    const out = parsed && parsed.stdout ? parsed.stdout : result;
    const lines = out.trim().split('\\n').filter(l => l.trim());
    return lines.slice(0, 3).join('\\n') + (lines.length > 3 ? `\\n… (${lines.length} lines)` : '');
  }
  if (tool === 'explore_dataset' || tool === 'statistics' || tool === 'explore') {
    const lines = result.split('\\n').filter(l => l.trim() && !l.startsWith('#'));
    return lines.slice(0, 3).join('\\n');
  }
  if (tool === 'vision_analyze') {
    const desc = parsed && parsed.description ? parsed.description : result;
    return String(desc).slice(0, 120);
  }
  const first = result.trim().split('\\n').find(l => l.trim()) || '';
  return first.slice(0, 120);
}

function logActivity(type, label, detail, imgPath) {
  const log = document.getElementById('activity-log');
  const div = document.createElement('div');
  div.className = `activity-item ${type}`;
  const icon = type === 'tool_call' ? '→' : '✓';
  const detailHtml = detail ? `<div class="detail">${escHtml(detail)}</div>` : '';
  const imgHtml = imgPath ? plotImgHtml(imgPath) : '';
  div.innerHTML = `<div class="label">${icon} ${escHtml(label)}</div>${detailHtml}${imgHtml}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function logSubActivity(type, subagent, tool, detail, imgPath) {
  const log = document.getElementById('activity-log');
  const div = document.createElement('div');
  div.className = `activity-item ${type}`;
  const icon = type === 'sub_call' ? '↳' : '↵';
  const prefix = `${escHtml(subagent)}/${escHtml(tool)}`;
  const detailHtml = detail ? `<div class="detail sub-indent">${escHtml(detail)}</div>` : '';
  const imgHtml = imgPath ? plotImgHtml(imgPath) : '';
  div.innerHTML = `<div class="label">${icon} ${prefix}</div>${detailHtml}${imgHtml}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function appendMessage(role, content) {
  const messages = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') {
    div.innerHTML = renderMarkdown(content);
  } else {
    div.textContent = content;
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Markdown renderer — delegates to marked.js (loaded from CDN)
function renderMarkdown(md) {
  return marked.parse(md);
}

// ── Send message ───────────────────────────────────────────────────────────────
function sendMessage() {
  const input = document.getElementById('user-input');
  const text = input.value.trim();
  if (!text) return;

  if (waitingForAnswer) {
    // Route as answer to the agent's ask_user question
    appendMessage('user', text);
    ws.send(JSON.stringify({type: 'user_answer', content: text}));
    input.value = '';
    waitingForAnswer = false;
    thinking = true;
    document.getElementById('send-btn').disabled = true;
    document.getElementById('user-input').placeholder = 'Type a message... (Enter to send, Shift+Enter for newline)';
    setStatus('thinking', 'Thinking...');
    return;
  }

  if (thinking) return;
  appendMessage('user', text);
  ws.send(JSON.stringify({type: 'user_message', content: text}));
  input.value = '';
  thinking = true;
  setStatus('thinking', 'Thinking...');
  document.getElementById('send-btn').disabled = true;
}

document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('user-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// ── Draggable divider between chart and panel ────────────────────────────────
(function() {
  const divider = document.getElementById('pm-divider');
  let dragging = false, startX = 0, startPanelW = 0;
  divider.addEventListener('mousedown', e => {
    dragging = true;
    startX = e.clientX;
    const panel = document.getElementById('pm-panel');
    startPanelW = panel.getBoundingClientRect().width;
    divider.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const delta = startX - e.clientX;  // dragging left = wider panel
    const newW = Math.max(200, Math.min(600, startPanelW + delta));
    document.getElementById('pm-panel').style.width = newW + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    divider.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    // Trigger Plotly resize so chart fills the new width
    Plotly.Plots && Plotly.Plots.resize && Plotly.Plots.resize('plot-modal-chart');
    window.dispatchEvent(new Event('resize'));
  });
})();

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  try {
    await loadProjects();
    await loadSessions();
  } catch(e) {
    console.warn('Could not load projects/sessions:', e);
  }
  connect();
}

init();
</script>
</body>
</html>
"""


@app.get("/api/projects/{project}/patterns")
async def get_patterns(project: str):
    """Return known pattern names for the pattern-checkbox panel."""
    import config
    project_dir = Path(config.PROJECTS_DIR) / project
    pat_path = project_dir / "feedback" / "pattern_names.json"
    if pat_path.exists():
        try:
            data = json.loads(pat_path.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass
    # Fall back: extract from feedback.json
    fb_path = project_dir / "feedback" / "feedback.json"
    if fb_path.exists():
        try:
            entries = json.loads(fb_path.read_text())
            seen, result = set(), []
            for e in entries:
                for p in e.get("pattern", []):
                    if p not in seen:
                        seen.add(p); result.append(p)
            return result
        except Exception:
            pass
    return []


async def _save_label_channels(msg: dict, project_dir: Path) -> dict:
    """Save channel labels to feedback/labels.json and return updated rejected/accepted sets."""
    trial_idx = int(msg.get("trial_idx") or 0)
    channels   = [int(c) for c in msg.get("channels", [])]
    patterns   = msg.get("patterns", ["artifact"])
    category   = msg.get("category", "reject")
    description = msg.get("description", "")

    labels_path = project_dir / "feedback" / "labels.json"
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if labels_path.exists():
        try:
            existing = json.loads(labels_path.read_text())
        except Exception:
            pass

    for ch in channels:
        sig_id = f"t{trial_idx:03d}_ch{ch:03d}"
        existing[sig_id] = {
            "category": category, "patterns": patterns,
            "description": description, "trial": trial_idx, "channel": ch,
        }

    labels_path.write_text(json.dumps(existing, indent=2))

    # Save new pattern names to registry
    if patterns:
        pat_path = project_dir / "feedback" / "pattern_names.json"
        known: list = []
        if pat_path.exists():
            try:
                known = json.loads(pat_path.read_text())
            except Exception:
                pass
        changed = False
        for p in patterns:
            if p not in known:
                known.append(p); changed = True
        if changed:
            pat_path.write_text(json.dumps(known, indent=2))

    prefix = f"t{trial_idx:03d}_"
    rejected = [int(v["channel"]) for k, v in existing.items()
                if k.startswith(prefix) and v.get("category") == "reject"]
    accepted = [int(v["channel"]) for k, v in existing.items()
                if k.startswith(prefix) and v.get("category") == "accept"]
    return {"trial_idx": trial_idx, "rejected": rejected, "accepted": accepted}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        import traceback
        from pathlib import Path
        from memory.backend import get_memory_backend
        from session.session import Session
        from orchestrator.loop import run
        import config

        # First message from client is always an "init" with project/session selection
        init_raw = await ws.receive_text()
        init_msg = json.loads(init_raw)
        project = init_msg.get("project", "default") if init_msg.get("type") == "init" else "default"
        session_id = init_msg.get("session_id", "new") if init_msg.get("type") == "init" else "new"

        try:
            # Sanitize project name
            safe_project = re.sub(r"[^\w\-]", "_", project.strip()) or "default"
            project_dir = (Path(config.PROJECTS_DIR) / safe_project).resolve()
            project_dir.mkdir(parents=True, exist_ok=True)
            memory_backend = get_memory_backend(project_dir)

            # Load or create session
            if session_id and session_id != "new":
                try:
                    session = Session.load(project_dir, session_id)
                except Exception:
                    session = Session(project_dir)
            else:
                session = Session(project_dir)

            # Build session label
            try:
                session_dt = datetime.strptime(session.session_id, "%Y%m%d_%H%M%S")
                session_label = session_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                session_label = session.session_id

            # Notify client of session details
            await ws.send_text(json.dumps({
                "type": "session_info",
                "project": safe_project,
                "session_id": session.session_id,
                "label": session_label,
                "turns": len(session.turns),
            }))
        except Exception as setup_exc:
            tb = traceback.format_exc()
            print(f"[WS setup error] {setup_exc}\n{tb}")
            await ws.send_text(json.dumps({"type": "error", "message": f"Server setup error: {setup_exc}"}))
            return

        async def on_event(event: dict):
            await ws.send_text(json.dumps(event))

        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") != "user_message":
                continue

            user_input = msg["content"]
            await ws.send_text(json.dumps({"type": "thinking"}))

            # Use a queue so the orchestrator can pause on ask_user and receive
            # the typed answer from the browser without blocking the WS reader.
            answer_queue: asyncio.Queue = asyncio.Queue()
            orch_task = asyncio.create_task(run(
                user_input=user_input,
                session=session,
                project_dir=project_dir,
                memory_backend=memory_backend,
                on_event=on_event,
                answer_queue=answer_queue,
            ))

            try:
                # While the orchestrator runs, keep reading incoming WS messages
                # so we can forward user_answer replies without deadlocking.
                while not orch_task.done():
                    try:
                        raw = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
                        inner = json.loads(raw)
                        if inner.get("type") == "user_answer":
                            await answer_queue.put(inner["content"])
                        elif inner.get("type") == "label_channels":
                            result = await _save_label_channels(inner, project_dir)
                            await ws.send_text(json.dumps({"type": "labels_saved", **result}))
                        # ignore user_message and other types while agent is running
                    except asyncio.TimeoutError:
                        pass

                response = orch_task.result()
                session.append(user_input, response)
                session.save()
                await ws.send_text(json.dumps({"type": "response", "content": response}))
            except WebSocketDisconnect:
                orch_task.cancel()
                raise
            except Exception as exc:
                if not orch_task.done():
                    orch_task.cancel()
                msg_str = str(exc)
                if "529" in msg_str or "overloaded" in msg_str.lower():
                    err = "Anthropic API overloaded — please try again in a moment."
                elif "rate" in msg_str.lower() or "429" in msg_str:
                    err = "Rate limited — wait a moment and try again."
                elif "internal server error" in msg_str.lower() or "500" in msg_str or "api_error" in msg_str:
                    err = "Anthropic API returned a transient 500 error — just retry your message."
                else:
                    err = f"Error: {type(exc).__name__}: {msg_str[:200]}"
                await ws.send_text(json.dumps({"type": "error", "message": err}))

    except WebSocketDisconnect:
        manager.disconnect(ws)
