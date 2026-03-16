<p align="center">
  <img src="image/icon.png" alt="AI Data Technician" width="200">
</p>

# AI Data Technician

An agentic AI system that learns from scientist interaction to inspect, analyze, and classify high-dimensional time series data — with persistent memory that improves across sessions.

---

## The Problem

Scientists across neuroscience, physiology, and sensor engineering routinely work with high-dimensional, high-sample-rate time series: multi-channel neural recordings at 1-2 kHz, wearable sensor streams, industrial vibration data. These signals share a set of hard problems:

- **Raw data is not directly consumable.** Thousands of samples per second across dozens of channels exceed both human inspection capacity and LLM context windows. Neither can reason productively about streams of raw numbers.
- **Expert knowledge is required but doesn't scale.** Identifying artifacts, marking events, classifying signal states — these tasks demand domain expertise applied to every segment of every channel. Manual inspection is the bottleneck.
- **No universal rules exist.** What constitutes "muscle artifact" or "clean signal" depends on hardware, electrode placement, brain region, patient population, and the scientist's specific goals. Thresholds and feature combinations vary across datasets and researchers.
- **Current AI can't bridge the gap alone.** LLMs have domain knowledge from literature but can't directly process raw sensor data. Vision models can analyze plots but don't know which features matter for a given task.

## The Approach

This system bridges the gap between raw data and expert judgment through five key ideas:

1. **Intermediate representations make data AI-readable.** Spectrograms, power spectral density plots, statistical features (kurtosis, line length, spectral edge frequency), and vision encoder embeddings compress time series into formats both humans and LLMs can reason about.

2. **Scientific tasks reduce to pattern detection + conditional action.** Artifact rejection, event marking, state classification, signal quality assessment — they all share the same structure: find segments matching a pattern, then apply an action (include, exclude, flag, transform). The patterns and actions vary; the computational structure does not.

3. **If a human can see it, we can compute it.** Any pattern visually distinct to a scientist has computable features — either mathematical (spectral power, entropy) or perceptual (cosine similarity in a vision embedding space). When existing features fail, the agent derives new ones.

4. **LLM agents formalize expert knowledge into interpretable rules.** The agent translates natural language descriptions and visual examples into feature selections, threshold values, and boolean logic. It uses evolutionary search (mutation, crossover, threshold optimization) to refine rules against human feedback — producing interpretable decision trees, not black boxes.

5. **LLM domain priors reduce human effort.** Knowledge from scientific literature provides strong priors on which features matter for specific pattern types, enabling meaningful rule proposals from descriptions and few examples. Active learning selects maximally informative examples from rule disagreement zones, further reducing labeling requirements.

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

## Why Memory Matters

Without persistent memory, every AI session starts from scratch — re-exploring datasets, re-discovering patterns, re-learning preferences. Memory transforms the system from a stateless tool into a **self-improving research assistant**.

What gets remembered:
- **Processing parameters** — spectrogram settings, filter configurations, visualization preferences
- **Signal patterns** — artifact signatures, pathological features, clean signal characteristics (with example signal IDs, channels, and anatomy)
- **Procedures** — analysis workflows, data loading scripts, labeling protocols
- **Domain knowledge** — terminology, detection rules, feature definitions

### Memory Architecture

| Layer | Scope | What it captures |
|-------|-------|------------------|
| **Session** | Current conversation | Chat turns, tool outputs, task progress |
| **Project** | Across sessions | Dataset-specific findings, parameters, labeled examples |
| **Global** | Across projects | Reusable procedures, cross-dataset insights |

Two backends are available:

- **File backend** — stores `project_memory.md` as plain markdown. Human-readable, git-trackable, works out of the box.
- **EverMemOS** — persistent semantic memory with hybrid retrieval (keyword + embedding search). Run [locally via Docker](https://github.com/nicholasgasior/evermemos) or use the managed cloud service.
- **Hybrid** — writes to both. Git-trackable files plus semantic search.

The orchestrator auto-compacts conversation context at ~40k tokens and periodically updates project memory every 5 user messages — knowledge is extracted continuously, not just at session end.

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

**Two-agent architecture:** An Orchestrator (Claude Sonnet, extended thinking) plans and delegates, while a Task agent autonomously executes multi-step work in up to 15 tool-use iterations. A Think agent handles reasoning, memory extraction, and context compaction.

## Tools

| Tool | What it does |
|------|-------------|
| `bash` | Run Python scripts, shell commands, install packages |
| `read` | Read text files, PDFs (text extraction), MATLAB `.mat` files (v4-v7.3) |
| `write` | Create/update files inside the project directory |
| `vision` | Analyze images via Gemini Flash (single or multi-image comparison) |
| `plot` | Plotly (interactive) or matplotlib (static PNG, auto-captured) |
| `recall` | Search long-term memory for past findings, procedures, parameters |
| `remember` | Save knowledge to long-term memory (parameters, patterns, procedures) |
| `task` | Delegate multi-step work to an autonomous sub-agent |
| `ask` | Clarifying questions via browser modal |
| `todo` | Structured task tracking with evidence requirements |

**Pre-installed scientific stack:** NumPy, SciPy, pandas, scikit-learn, MNE, antropy, ruptures, h5py, mat73, matplotlib, plotly.

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
