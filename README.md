<p align="center">
  <img src="image/icon.png" alt="AI Data Technician" width="200">
</p>

# AI Data Technician

An agentic AI system that learns from scientist interaction to inspect, analyze, and classify high-dimensional time series data — with persistent memory that improves across sessions.
**A video demonstration of the system can be found here: https://www.youtube.com/watch?v=k1L-xqT8Owo**

---

## Motivation

Scientists across neuroscience, physiology, and sensor engineering routinely work with high-dimensional, high-sample-rate time series — multi-channel neural recordings at 1-2 kHz, wearable sensor streams, industrial vibration data. Raw samples exceed both human inspection capacity and LLM context windows, yet the core tasks (artifact rejection, event marking, signal classification) all demand domain expertise applied at scale. No universal thresholds exist — what counts as "muscle artifact" or "clean signal" varies by hardware, brain region, patient population, and analytical goals.

This system bridges the gap by converting raw time series into intermediate representations (spectrograms, PSD plots, statistical features) that both humans and LLMs can reason about, then using interactive human-AI collaboration to formalize expert knowledge into interpretable detection rules. Persistent memory ensures that learned parameters, signal patterns, and processing procedures carry across sessions, creating a system that improves with every interaction.

---

## Features

### Three-Agent Architecture

The system runs on three specialized agents that coordinate to plan, execute, and learn:

**Orchestrator Agent** — The decision-maker. Powered by Claude Sonnet with extended thinking (4,000-token reasoning budget), the Orchestrator receives each user message, reasons about what needs to happen, and decides whether to call a tool directly, delegate to the Task agent, or respond. It maintains the full conversation context, manages the tool-use loop (up to 25 iterations for complex requests), and decides when to recall from memory or save new knowledge. Extended thinking gives it a private scratchpad to plan multi-step analyses before acting — for example, deciding which signals to sample, what statistics to compute, and how to present results, all before making the first tool call.

**Task Agent** — The workhorse. When the Orchestrator encounters multi-step work — exploring a dataset, running a statistical analysis across dozens of files, generating and testing code — it delegates to the Task agent. The Task agent gets a fresh context with its own tool-use loop (up to 15 iterations) and access to `bash`, `read`, `write`, and `vision`. It works autonomously: loading files, computing features, writing results, and returning a final summary. Because it runs independently, the Orchestrator can continue reasoning about the bigger picture while the Task agent handles the details. The Orchestrator injects all necessary context (file paths, column names, data formats, prior findings) into the task description so the Task agent can work without access to the conversation history.

**Think Agent** — The knowledge keeper. A single-pass reasoning agent (no tools) with a 3,000-token thinking budget, the Think agent handles three critical functions:
1. **Memory extraction** — Every 5 user messages, the Think agent reviews recent conversation turns and updates `project_memory.md` with new findings, pruning stale facts and consolidating to stay under 5,000 tokens.
2. **Context compaction** — When the conversation exceeds 40,000 tokens, the Think agent summarizes the oldest 20 turns into a ~200-word paragraph that preserves key findings, metrics, and decisions. This keeps the context window fresh without losing information.
3. **Session reflection** — When a session ends, the Think agent reviews the full conversation and promotes reusable procedures, user preferences, and cross-project insights to global memory.

### Tools

| Tool | What it does |
|------|-------------|
| `bash` | Execute Python scripts, shell commands, or install packages via PowerShell (Windows) or shell (Unix). Supports timeouts and environment variable injection. |
| `read` | Read text files with optional offset/limit paging. Extracts text from PDFs (via PyMuPDF) and loads MATLAB `.mat` files (v4 through v7.3 via scipy and h5py), returning structure and shape information. |
| `write` | Create or update files inside the project directory. Path-restricted — refuses to write outside the project boundary. |
| `vision` | Send one or more images (up to 5) to Gemini Flash for structured analysis. Supports single-image description and multi-image comparison with named references. The system injects project memory into the vision prompt so the model can reference known patterns and parameters. |
| `plot` | Generate charts displayed in the browser. Two modes: **Plotly (interactive)** — code produces a figure dict printed as JSON, rendered as a zoomable/pannable chart with hover tooltips. **Matplotlib (static)** — code creates figures normally; a preamble auto-applies dark theme and an epilogue captures all open figures as base64 PNG, displayed inline with a lightbox. |
| `recall` | Search long-term memory across both project and global layers. Three-phase process: (1) retrieve matching memories via keyword + semantic search, (2) emit results to the UI, (3) synthesize findings through the Think agent into a coherent summary that distinguishes project-specific vs. cross-project knowledge. |
| `remember` | Explicitly save knowledge to long-term memory. Stores content with descriptive tags for future retrieval. Supports `project` scope (dataset-specific) or `global` scope (cross-project). In hybrid mode, writes to both file and EverMemOS simultaneously. |
| `task` | Delegate multi-step work to an autonomous Task agent. The orchestrator packs all necessary context into the description — the Task agent cannot see the conversation. Useful for exploration, statistical analysis, code generation, and evaluation. |
| `ask` | Pause execution and ask the user a clarifying question via a browser modal. The agent waits (up to 10 minutes) for the user's response before continuing. Used only when genuinely blocked. |
| `todo` | Create or update a structured task list for the current session. Each item has an ID, description, and status (`pending` → `running` → `done`/`failed`). Evidence from tool output is mandatory for marking items done or failed — no reasoning-only completions. |

**Pre-installed scientific stack:** NumPy, SciPy, pandas, scikit-learn, MNE, antropy, ruptures, h5py, mat73, matplotlib, plotly, statsmodels, scikit-image.

### Real-Time Web Interface

The browser-based UI connects via WebSocket for real-time streaming — no polling, no page refreshes.

- **Chat panel** — Messages stream in token-by-token as the agent generates them. Markdown rendered with sanitized HTML (XSS-safe via DOMPurify).
- **Activity panel** — A sidebar showing live tool calls and results as they happen. Color-coded labels distinguish orchestrator tools (blue), sub-agent calls (purple), and results (green). Memory recalls and saves appear with their content.
- **Interactive plots** — Plotly charts open as modals with full zoom, pan, and hover. Matplotlib figures display inline with a lightbox for detailed inspection.
- **Ask modal** — When the agent needs clarification, a question appears in the chat with an input field. The agent pauses until you respond.
- **Todo tracker** — The task list appears at the top of the activity panel, updating in real-time as the agent works through steps.
- **Status indicator** — A colored dot shows connection state (green = connected, amber = agent is thinking).

---

## Memory System

Without persistent memory, every AI session starts from scratch. Memory transforms the system from a stateless tool into a self-improving research assistant that remembers how to load your data, which parameters work best, what artifacts look like, and what procedures you prefer.

What gets remembered: **processing parameters** (spectrogram settings, filter configs, with rationale and example code), **signal patterns** (artifact signatures, pathological features, with example signal IDs and anatomy), **procedures** (analysis workflows, labeling protocols), and **domain knowledge** (terminology, detection rules, dataset metadata).

### Three-Layer Architecture

| Layer | Scope | File Storage | EverMemOS Storage |
|-------|-------|-------------|-------------------|
| **Session** | Current conversation | `sessions/session_{id}.json` — every turn, tool call, result, and todo list. Saved after each turn. | Raw chat turns logged via `store_chat_turn()` for passive fact extraction. |
| **Project** | Across sessions, one project | `project_memory.md` — structured markdown updated by the Think agent every 5 messages. Injected into the orchestrator's system prompt each turn. | Memories stored with project-scoped `group_id` (hash of project path). Classified as `episodic_memory` (findings, parameters, patterns) or `profile` (user preferences). Keyword-indexed for semantic retrieval. |
| **Global** | Across all projects | `projects/_global/global_memory.md` — populated by end-of-session reflection. | Stored under `adt_global` group_id. Contains reusable procedures, user preferences, and cross-project insights. |

Project and global memory are both injected into the orchestrator's context at the start of every turn — the agent has full knowledge from prior sessions without needing to recall explicitly.

### Memory Lifecycle

```
  User teaches something
         |
         v
  Orchestrator calls `remember` ──> File: written to project_memory.md
         |                           EverMemOS: extracted into keyword-indexed
         |                           episodic_memory with tags for retrieval
         v
  Every 5 messages ────────────────> Think agent reviews recent turns,
         |                           merges new findings into project_memory.md,
         |                           prunes stale facts (≤500 words/section)
         v
  Passive extraction ──────────────> EverMemOS receives raw chat turns,
         |                           auto-extracts facts the agent didn't
         |                           explicitly save (hybrid backend)
         v
  Session ends ────────────────────> Think agent reflects on full session.
         |                           Promotes to global memory:
         |                           • reusable procedures → global file + EverMemOS
         |                           • user preferences → global file + EverMemOS
         |                           • cross-project insights → global file + EverMemOS
         v
  Next session starts ─────────────> project_memory.md + global_memory.md
         |                           loaded into system prompt.
         v                           `recall` tool queries EverMemOS for
  Agent recalls as needed             semantic search when deeper retrieval needed.
```

### EverMemOS Integration

[EverMemOS](https://github.com/nicholasgasior/evermemos) is an open-source persistent memory service for AI agents. It adds semantic understanding and intelligent retrieval on top of the file-based memory layer.

**How it works:**

1. **Store.** When a memory is saved (`POST /memories`), EverMemOS processes the text, extracts discrete facts, and indexes them with keywords and timestamps. "Muscle artifact shows broadband power above 80 Hz in temporal channels" becomes a searchable entry tagged with `muscle artifact`, `broadband`, `80 Hz`, `temporal`.

2. **Retrieve.** The `recall` tool sends natural language queries to `/memories/search`. EverMemOS finds conceptually related memories — not just exact keyword matches. Asking "how should I detect artifacts?" returns memories about thresholds, frequency characteristics, and anatomy-specific patterns. Results include full metadata (content, memory type, keywords, timestamp, group_id) for the Think agent to synthesize.

3. **Scope.** Each project gets a deterministic `group_id` so memories never leak between projects. Global memory uses a special `adt_global` group_id.

4. **Session init.** At session start, conversation metadata is registered — project name, participant roles (AI Data Technician / Researcher), and tags — so EverMemOS maintains context about who said what.

**Memory types:** `episodic_memory` (findings, summaries, observations) and `profile` (plot preferences, channel selections, communication style).

**Deployment:** Run locally via Docker (`docker run -p 1995:1995 ghcr.io/nicholasgasior/evermemos:latest`) or use the managed cloud service at `api.evermind.ai`. The system handles API differences automatically.

### Memory Backends

| Backend | Writes to | Reads from | Best for |
|---------|-----------|------------|----------|
| **File** | `project_memory.md` | Full-text (entire document) | Simple setup, git-trackable |
| **EverMemOS** | EverMemOS API | Semantic search | Intelligent retrieval at scale |
| **Hybrid** (default) | Both simultaneously | EverMemOS with file fallback | Durability + semantic search |

The hybrid backend writes to the file first (synchronous, reliable), then to EverMemOS (best-effort). If EverMemOS is unreachable, the system falls back to file-based memory — it never crashes or loses data due to a backend outage.

### Quality Control

The **memory gate** controls update frequency — rather than updating on every message, it waits until enough new information accumulates (configurable via `MEMORY_UPDATE_INTERVAL`), then sends recent turns to the Think agent to merge findings, prune stale facts, and keep each section under 500 words. The **todo system** requires evidence from actual tool results to mark items done — no reasoning-only completions — ensuring memory entries are grounded in real observations.

---

## Demo: iEEG Analysis (MayoData1000)

The following screenshots are from a real analysis session on the [MayoData1000 multicenter iEEG dataset](https://doi.org/10.1038/s41597-020-0532-5) (1,000 intracranial EEG signals, 5 kHz, 3 seconds each, SOZ-labeled).

### 1. Explore — Visualize and inspect signals

The scientist asks for a time series, spectrogram, and PSD of a hippocampal signal. The system loads the `.mat` file, computes all three views, and renders them in the browser.

<p align="center">
  <img src="image/plotting.png" alt="iEEG signal visualization — time series, spectrogram, and PSD" width="800">
</p>

### 2. Teach — Identify and document signal patterns

The scientist points out artifact examples. The system analyzes them visually (via vision model) and statistically, documenting the distinguishing features of each artifact type.

<p align="center">
  <img src="image/teach_signalpattern.png" alt="Teaching artifact patterns — muscle artifact and powerline contamination" width="800">
</p>

### 3. Remember — Save learned knowledge to memory

After the scientist approves a set of spectrogram parameters or artifact definitions, the system saves them to persistent memory — including parameter values, rationale, and example code.

<p align="center">
  <img src="image/remember_parameter.png" alt="System saving optimized spectrogram parameters to memory" width="800">
</p>

### 4. Recall — Apply knowledge in future sessions

In a new session, the scientist asks the system to plot spectrograms. The system recalls the previously optimized parameters from memory and applies them without re-learning.

<p align="center">
  <img src="image/recall_parameter.png" alt="System recalling spectrogram parameters from memory" width="800">
</p>

The system can also synthesize everything it knows about a signal pattern — combining findings from past sessions, the original paper, and domain knowledge into a comprehensive summary.

<p align="center">
  <img src="image/recall_signalpattern.png" alt="System recalling synthesized knowledge about pathological signals" width="800">
</p>

---

## Architecture

```
User (Browser)
    |  WebSocket (real-time streaming)
    v
+----------------+
|  FastAPI Web   |  interface/web.py
|  Server        |  Session & project management
+-------+--------+
        |
        v
+----------------+     +---------------+
| Orchestrator   |---->| Task Agent    |  Up to 15 iterations
| (Claude,       |     | (bash, vision |  autonomous tool-use
|  ext. thinking)|     |  read, write) |
|                |     +---------------+
| Plans &        |
| delegates      |---->  Tools (bash, read, plot, vision, ask, todo)
|                |
|                |---->  Think Agent (reasoning, memory updates, compaction)
+-------+--------+
        |
        v
+----------------------------------------------+
|              Memory Backend                   |
|  File (markdown) | EverMemOS (semantic search)|
|                                               |
|  Session JSON - project_memory - global_memory|
+----------------------------------------------+
```

---

## Quick Start

### Prerequisites

- [Pixi](https://pixi.sh) (conda-based package manager)
- An [Anthropic API key](https://console.anthropic.com/) (Claude)
- A [Google API key](https://aistudio.google.com/apikey) (Gemini Flash, for vision)
- *(Optional)* [Docker](https://docker.com) — for running EverMemOS locally

### Setup

```bash
# Clone and install
git clone git@github.com:yuansui123/AI-Data-Technician.git
cd AI-Data-Technician
pixi install

# Configure API keys
cp .env.template .env
# Edit .env: ANTHROPIC_API_KEY=sk-ant-...  GOOGLE_API_KEY=AIza...

# Launch
pixi run web
# Open http://localhost:8000
```

### CLI Options

```
python main.py [OPTIONS]

--project NAME    Project name (default: "default")
--start           Initialize a new project directory
--port N          Web UI port (default: 8000)
--debug           Log all LLM I/O to logs/
```

### Enabling EverMemOS

```bash
# Local (Docker)
docker run -p 1995:1995 ghcr.io/nicholasgasior/evermemos:latest
# Set MEMORY_BACKEND = "evermemos_local" in config.py

# Cloud
# Add EVERMEM_API_KEY=your-key to .env
# Set MEMORY_BACKEND = "evermemos_cloud" in config.py

# Hybrid (both file + EverMemOS)
# Set MEMORY_BACKEND = "hybrid" in config.py
```

---

## Configuration

All settings in [`config.py`](config.py):

| Setting | Default | Description |
|---------|---------|-------------|
| `ORCHESTRATOR_MODEL` | `claude-sonnet-4-6` | Main orchestrator model |
| `THINK_MODEL` | `claude-sonnet-4-6` | Reasoning & memory model |
| `VISION_MODEL` | `gemini-2.5-flash` | Image analysis model |
| `MEMORY_BACKEND` | `"hybrid"` | `"file"`, `"evermemos_local"`, `"evermemos_cloud"`, or `"hybrid"` |
| `ORCHESTRATOR_THINKING` | `4000` | Extended thinking token budget |
| `TASK_MAX_ITER` | `15` | Max tool-use iterations per task |
| `AUTO_COMPACT_THRESHOLD` | `40000` | Token count triggering compaction |
| `MEMORY_UPDATE_INTERVAL` | `5` | User messages between memory updates |

---

## License

MIT
