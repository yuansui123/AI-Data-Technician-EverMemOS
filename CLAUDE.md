# AI Data Technician

## What this project is
A local-first AI agent system for analyzing raw time series data (EEG/neural signals). Architecture modeled on Claude Code: tools + agents + workflows.

**Read the full architecture plan before doing anything**: `.claude/PLAN.md`

---

## Key external dependencies (path imports — do not copy)
```
C:\Users\yuans\Desktop\ClaudeCode\v4cedars\lib\
    feature_store.py, label_store.py, rules.py, workflow.py
    features\*, plot\*, gui\*
```
All imports from v4cedars use this path. Never duplicate these files here.

---

## Local libraries (`lib/`)

- `lib/lasr/` — LASR optimization engine (evaluation, evolution, pareto, population, sampling). Copied from v4cedars with imports updated. Import as `from lib.lasr import ...`.

---

## Architecture: tools / agents / workflows

**Tools** (`tools/`) — deterministic, no LLM:
- `bash.py` — subprocess execution via PowerShell
- `vision.py` — Gemini Flash, image(s) → structured JSON. Supports up to 5 named images for comparative analysis.
- `read.py` — file reader with paging
- `write.py` — file writer with project directory safety guard
- `ask.py` — human-in-the-loop input
- `todo.py` — session task list schema (executor in orchestrator)
- `plot.py` — Plotly chart schema (executor in orchestrator)

`tools/__init__.py` exports `TOOL_SCHEMAS` (all 7 tool schemas), `EXPLORE_TOOLS`, and `STATISTICS_TOOLS`.

**Agents** (`agents/`) — all LLM invocations via `invoke()`:
- `runner.py` — core LLM loop engine (`invoke()`, `run_agent()`, `SubagentConfig`, `ToolExecutor`)
- `think.py` — single-pass Claude + extended thinking (summaries, compaction, LASR prompts)
- `explore.py` — tool-use loop [Bash, Vision, Read, Write], max 10 iter
- `statistics.py` — tool-use loop [Bash, Vision, Read, Write], max 15 iter
- `codegen.py` — generate→run→fix loop for Plotly scripts
- `code.py` — single-pass code writer (feature/plot functions)

**Workflows** (`workflows/`) — Python async sequences composing tools + agents:
- `explore_dataset`, `ingest_documents`, `optimize_pattern`
- `teach_session`, `review_results`, `apply_rules`

**Orchestrator** (`orchestrator/loop.py`) — the outer LLM agent loop. Imports `TOOL_SCHEMAS` from `tools/` and combines with inline agent/workflow schemas.

---

## Context management
- `project_memory.md` per project — agent-maintained by Think after milestones
- `sessions/session_{id}.json` — conversation turns, one per session
- Auto-compact via Think when context > 40k tokens
- In-context todo list maintained by orchestrator
- `context_carry` dict passes facts between agent steps

---

## Memory backend
- Default: `FileMemoryBackend` — reads/writes `project_memory.md`
- Future: `EverMemOSBackend` at `localhost:1995/api/v1` — swap via `MEMORY_BACKEND` in `config.py`
- Orchestrator only calls `memory_backend.store()` / `memory_backend.get_summary()`

---

## Hallucination prevention
- Each agent gets a **fresh bounded context** assembled by orchestrator
- Hard iteration limits at every level (Orchestrator: 8/20/50, Explore: 10, Statistics: 15, CodeGen: 8)
- Extended thinking replaces long reasoning chains within a single call
- Think agent post-processes results into compact summaries before entering orchestrator context
- Termination enforced at infrastructure level, not by LLM self-termination

---

## Coding conventions
- All LLM calls go through `agents/runner.py:invoke()`
- Tools never call agents or other tools
- Agents use [Bash, Vision, Read, Write] as tools — never other agents
- Workflows are plain Python async functions — no LLM at the workflow level
- Tool definitions live in `tools/` as Anthropic JSON schema dicts
- System prompts live in `agents/prompts/*.md`
- `config.py` is the single source of truth for model IDs, token budgets, and paths
