# AI Data Technician — Architecture Plan

## Context

Synthesizing two existing approaches into a single local-first system:
- **v16CodeAct** (`C:\Users\yuans\Desktop\Mayo_dataset\agent_datacleaning\v16CodeAct`): Visualization agent, LangGraph 4-node loop. Hallucination root cause: unbounded 500-step context accumulation, no token ceiling, LLM-compliance-dependent termination.
- **v4cedars** (`C:\Users\yuans\Desktop\ClaudeCode\v4cedars`): Statistics/rules agent via Claude Code + 5 skills. LASR evolutionary rule optimization. Works well: interpretable boolean rules, project-scoped file state, human-in-the-loop GUI.

Goal: Local-first, single-user system modeled on Claude Code's architecture (tools + agents + workflows). File-based memory now; EverMemOS pluggable later via abstraction layer.

---

## Context Management (modeled on Claude Code)

Claude Code uses: CLAUDE.md (static instructions) + growing conversation window + TodoWrite scratchpad + session files. No external DB.

We use the same model:

### project_instructions.md — static (our CLAUDE.md)
Created at `/start`, human-editable. Loaded at the start of every orchestrator run.
```
Contents: dataset description, sampling rate, file format,
          task definition, categories, known artifact types
Size: ~1-2k tokens, does not grow
```

### project_summary.md — agent-maintained living document
Updated by Think agent after every major milestone. Loaded every run.
```
Contents: what has been done, what was found, best rules per pattern,
          features added, labeling history, current accuracy
Size: starts small, grows slowly (~2-5k tokens over full project)
```
This replaces EverMemOS for cross-session continuity. Human-readable, git-trackable, editable.

### Session files — conversation turns (like Claude Code's ~/.claude/projects/)
```
sessions/session_{id}.json   # full conversation turns, one file per session

python main.py                     # new session: loads instructions + summary
python main.py --continue          # reload last session's turns
python main.py --session 20260312  # load specific session
```

### In-context scratchpad — TodoWrite equivalent
Markdown checklist maintained by orchestrator within the context window.
Also stored in `tmp/session_{id}/scratchpad.json` for persistence within session.

### context_carry — small fact-passing dict
Passes key outputs between agent steps without each agent seeing the full prior conversation:
```python
context_carry = {
    "fn_signals":  ["t002_ch041", "t003_ch012"],
    "feature_gap": "burst_rate in 80-150Hz band"
}
```

### Context assembly per user message
```python
async def run(user_input: str, session: Session):
    instructions = read("project_instructions.md")   # ~1-2k tokens, static
    summary      = memory_backend.get_summary()      # ~2-5k tokens
    turns        = session.turns                     # grows within session

    # auto-compact when context exceeds threshold (like Claude Code /compact)
    if token_count(instructions + summary + turns) > 40_000:
        compact = await think(oldest_turns(turns, n=20))
        turns   = [{"role": "summary", "content": compact}] + recent_turns(turns, n=5)
        session.replace_turns(turns)

    context  = instructions + summary + turns + session.scratchpad + user_input
    response = await orchestrator_loop(context, session)
    session.append(user_input, response)
    session.save()
    return response
```

---

## Memory Abstraction Layer

```python
# memory/backend.py
class MemoryBackend(ABC):
    async def store(self, content: str, metadata: dict) -> None: ...
    async def get_summary(self) -> str: ...
    async def retrieve(self, query: str, top_k: int = 5) -> str: ...

class FileMemoryBackend(MemoryBackend):
    """Current default. Reads/writes project_summary.md."""

class EverMemOSBackend(MemoryBackend):
    """Pluggable upgrade. Supports local Docker and cloud deployments."""
    # memory/evermemos.py — POST /memories, GET /memories/search
```

**Config switch** (`config.py`):
```python
MEMORY_BACKEND = "file"              # now
# MEMORY_BACKEND = "evermemos_local" # Docker at localhost:1995
# MEMORY_BACKEND = "evermemos_cloud" # api.evermind.ai
```

---

## Architecture: Tools / Agents / Workflows

### Orchestrator
- **Model**: claude-sonnet-4-6
- **Role**: Main loop. Interprets user intent, maintains scratchpad, dispatches agents/workflows, enforces iteration ceiling
- **Iteration limits**: simple=5, moderate=10, complex=25
- **Code**: `orchestrator/loop.py` — tool schemas + `OrchestratorToolExecutor` + `run()`

---

### Tools (`tools/`) — deterministic, no LLM

**bash.py** — subprocess execution via PowerShell
```python
async def bash(cmd: str, cwd: str = None, timeout: int = 60) -> BashResult
```

**vision.py** — Gemini 2.5 Flash, image → structured JSON
```python
async def vision(image_path, context=None) -> dict
# Returns: {description, likely_pattern, rule_assessment, suggested_feature_gap}
```

**read_file.py** — file reader with paging
```python
def read_file(path, max_chars=8000, offset_chars=0) -> dict
```

**ask_user.py** — human-in-the-loop input (CLI stdin or web answer_queue)

**lasr/** — LASR optimization code (copied from v4cedars, imports updated):
- `evaluation.py` — rule evaluation via safe eval()
- `evolution.py` — `numeric_mutate()` + 4 `format_*_prompt()` builders (mutation, crossover, concept abstraction, concept evolution)
- `pareto.py` — Pareto front extraction
- `population.py` — `Rule` dataclass + `RulePopulation`
- `sampling.py` — active learning signal selection

Note: `evolution.py` has **prompt builders** (`format_mutation_prompt`, `format_crossover_prompt`, `format_concept_abstraction_prompt`, `format_concept_evolution_prompt`) but no glue code to call an LLM. The `optimize_pattern` workflow should call `think()` with these prompts to get LLM-guided mutations.

---

### Agents (`agents/`) — all LLM invocations

All LLM calls go through `agents/runner.py:invoke()`. Single-pass agents use `max_iterations=1`. Multi-pass agents use `max_iterations>1` with a `ToolExecutor`.

**runner.py** — core LLM loop engine
- `SubagentConfig` dataclass (model, system_prompt, tools, thinking_budget, max_iterations, max_tokens)
- `SubagentResult` dataclass (text, thinking, tool_calls, iterations, usage)
- `ToolExecutor` class — dispatches bash_execute, vision_analyze, read_file
- `invoke()` — core loop with retry, streaming, tool execution
- `run_agent()` — high-level spawner (loads prompts from `agents/prompts/{name}.md`)

**think.py** — single-pass Claude + optional extended thinking
```
Model:    claude-sonnet-4-6, thinking budget configurable
Tools:    none
Output:   plain-language insight → memory_backend.store()
Also:     compact_turns() for auto-compact
```

**explore.py** — agentic tool-use loop
```
Model:    claude-sonnet-4-6
Tools:    [bash_execute, vision_analyze]
Output:   {n_signals, fs, duration_s, file_types, quality_flags, domain_notes, suggested_patterns}
Limit:    max 10 tool-use iterations
```

**statistics.py** — agentic tool-use loop, general quantitative reasoning
```
Model:    claude-sonnet-4-6
Tools:    [bash_execute, vision_analyze] + extra_tools
Output:   {findings, best_rule?, fitness?, fp_signals, fn_signals, plateau?, suggested_feature_gap?}
Limit:    max 15 tool-use iterations
```

**codegen.py** — generate→run→fix loop for Plotly scripts
```
Model:    claude-sonnet-4-6, thinking budget 2000
Tools:    [bash_execute, read_file, write_and_run]
Output:   working Python script body
Limit:    max 8 iterations
```

**code.py** — single-pass code writer (feature/plot functions)
```
Model:    claude-sonnet-4-6
Tools:    none
Output:   writes draft to tmp/code_drafts/
Limit:    1 API call
```

**Available approaches via Statistics agent's Bash tool:**
- LASR (`tools/lasr/`): rule optimization, mutation, crossover, pareto
- scipy/statsmodels: t-test, ANOVA, KS-test, distribution fitting, correlation
- sklearn: KMeans, DBSCAN, IsolationForest, PCA, UMAP
- ruptures: change point detection
- antropy/mne: entropy measures, EEG-specific analysis
- pandas/numpy: group statistics, feature distributions

---

### Workflows (`workflows/`) — predefined Python async sequences

```python
async def explore_dataset(data_dir, project_dir): ...
async def ingest_documents(file_paths, project_dir): ...
async def optimize_pattern(pattern_name, project_dir): ...
async def teach_session(project_dir): ...
async def review_results(project_dir): ...
async def apply_rules(project_dir): ...
```

Workflows compose tools and agents but contain **no LLM calls themselves** — they're pure Python async orchestration.

---

## Storage Layout

```
projects/{Name}/
├── project_instructions.md    ← static, created at /start
├── project_summary.md         ← agent-maintained by Think
├── sessions/
│   └── session_{id}.json      ← conversation turns per session
├── feedback/                  ← feedback.json, labels.json, screenshots/
├── patterns/{name}/           ← concept.md, exemplars.json, hypotheses.json
├── rules/classification.json
├── cache/                     ← feature_matrix.parquet, workflow_state.json
└── tmp/                       ← plots/, code_drafts/, session_{id}/scratchpad.json
```

---

## File Structure

```
AI_Data_Technician/
├── .claude/
│   ├── settings.local.json
│   └── PLAN.md                ← this file
│
├── CLAUDE.md                  ← auto-loaded by Claude Code
├── main.py                    # CLI: python main.py [--continue] [--session ID] [--web]
├── config.py                  # API keys, model IDs, budgets, MEMORY_BACKEND
├── requirements.txt
│
├── tools/                     # deterministic, no LLM
│   ├── __init__.py            # exports EXPLORE_TOOLS, STATISTICS_TOOLS
│   ├── bash.py                # subprocess execution
│   ├── vision.py              # Gemini Flash image analysis
│   ├── read_file.py           # file reader with paging
│   ├── ask_user.py            # human-in-the-loop input
│   └── lasr/                  # LASR optimization (local copy from v4cedars)
│       ├── evaluation.py
│       ├── evolution.py
│       ├── pareto.py
│       ├── population.py
│       └── sampling.py
│
├── agents/                    # all LLM invocations
│   ├── __init__.py            # exports SubagentConfig, invoke, run_agent, think, etc.
│   ├── runner.py              # core LLM loop engine (invoke, run_agent, ToolExecutor)
│   ├── think.py               # single-pass + compact_turns
│   ├── explore.py             # tool-use loop [Bash, Vision]
│   ├── statistics.py          # tool-use loop [Bash, Vision]
│   ├── codegen.py             # generate→run→fix loop
│   ├── code.py                # single-pass code writer
│   └── prompts/               # system prompt .md files
│       ├── orchestrator.md
│       ├── think.md
│       ├── explore.md
│       ├── statistics.md
│       ├── codegen.md
│       └── code.md
│
├── workflows/                 # Python async sequences (no LLM at workflow level)
│   ├── explore_dataset.py
│   ├── ingest_documents.py
│   ├── optimize_pattern.py
│   ├── teach_session.py
│   ├── review_results.py
│   └── apply_rules.py
│
├── orchestrator/
│   └── loop.py                # main agent loop, tool schemas, OrchestratorToolExecutor
│
├── memory/
│   ├── backend.py             # MemoryBackend ABC + FileMemoryBackend + get_memory_backend()
│   └── evermemos.py           # EverMemOSBackend (local + cloud)
│
├── session/
│   ├── session.py             # Session: turns, scratchpad, context_carry, save/load
│   └── context_builder.py     # assembles instructions+summary+turns+scratchpad
│
├── interface/
│   ├── cli.py                 # REPL with --continue / --session flags
│   └── web.py                 # FastAPI + WebSocket + HTML/JS UI
│
└── tests/

─── External path imports ───────────────────────────────────────────────
C:\Users\yuans\Desktop\ClaudeCode\v4cedars\lib\
    feature_store.py, label_store.py, rules.py, workflow.py,
    features\*, plot\*, gui\*
```

---

## Code Reuse

### From v4cedars — import directly, no modification
- `lib/features/` — `@feature` / `@plot` registry + auto-discovery
- `lib/feature_store.py`, `lib/label_store.py`
- `lib/rules.py`, `lib/workflow.py`
- `lib/plot/`, `lib/gui/`

### From v4cedars — copied locally to tools/lasr/
- `lib/optimization/` — evaluation, evolution, pareto, population, sampling
- Imports updated from `lib.optimization.*` to `tools.lasr.*`

### From v16 — selective
- `plot_power_density_matrix_hilbert()` → adapt to `@plot` decorator → `lib/plot/custom/`
- LangGraph, DualRAG, 500-step loop → **not reused**

---

## Verification

1. `python main.py` → new session, loads project_instructions.md + project_summary.md
2. "I have EEG data at C:/data/, here is the paper [PDF]" → ingest_documents → explore_dataset → Think updates project_summary.md
3. "optimize muscle_artifact" → Statistics → plateau → Vision×N → Think → Code → Bash → Statistics → Think updates summary
4. `python main.py` next day → project_summary.md loaded, agent resumes with full context
5. `python main.py --continue` → last session turns reloaded
6. "is gamma_power significantly different between classes?" → Statistics (scipy t-test) → p-value reported
7. Context > 40k tokens → auto-compact triggers → Think summarizes → context shrinks
8. `MEMORY_BACKEND = "evermemos_local"` in config → EverMemOS backend active
