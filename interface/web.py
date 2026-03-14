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

  /* Label modal — interactive signal labelling popup */
  #label-modal { display: none; position: fixed; inset: 0; z-index: 950;
                 background: rgba(0,0,0,.88); align-items: center; justify-content: center; }
  #label-modal.open { display: flex; }
  #label-modal-card { background: #1a1d27; border: 1px solid #2d3147; border-radius: 12px;
                      padding: 20px; max-width: min(820px, 92vw); width: 100%;
                      display: flex; flex-direction: column; gap: 12px; }
  #label-modal-header { display: flex; justify-content: space-between;
                        font-size: 12px; color: #6b7280; font-family: 'Consolas', monospace; }
  #label-modal-plot { width: 100%; height: 360px; }
  #label-modal-context { font-size: 12px; color: #94a3b8; }
  #label-modal-btns { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
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

<div id="label-modal">
  <div id="label-modal-card">
    <div id="label-modal-header">
      <span id="label-modal-progress"></span>
      <span id="label-modal-id"></span>
    </div>
    <div id="label-modal-plot"></div>
    <div id="label-modal-context"></div>
    <div id="label-modal-btns"></div>
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

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

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

  } else if (ev.type === 'label_signal') {
    clearThinkingEntry();
    showLabelModal(ev);

  } else if (ev.type === 'ask_user') {
    clearThinkingEntry();
    // Show question as assistant bubble in main chat
    appendMessage('assistant', ev.question);
    // Let user type an answer — briefly suspend "thinking" lockout
    waitingForAnswer = true;
    thinking = false;
    document.getElementById('send-btn').disabled = false;
    document.getElementById('user-input').placeholder = 'Type your answer and press Enter...';
    setStatus('thinking', 'Waiting for your answer...');
  }
}

function clearThinkingEntry() {
  if (thinkingEntry) { thinkingEntry.remove(); thinkingEntry = null; }
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
                    err = "Anthropic API overloaded. Check status.claude.com and try again."
                elif "rate" in msg_str.lower() or "429" in msg_str:
                    err = "Rate limited. Wait a moment and try again."
                else:
                    err = f"Error: {type(exc).__name__}: {msg_str[:200]}"
                await ws.send_text(json.dumps({"type": "error", "message": err}))

    except WebSocketDisconnect:
        manager.disconnect(ws)
