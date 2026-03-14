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

LASR optimization code (evaluation, evolution, pareto, population, sampling) has been copied locally to `tools/lasr/` with imports updated.

---

## Architecture: tools / agents / workflows

**Tools** (`tools/`) — deterministic, no LLM:
- `bash.py` — subprocess execution via PowerShell
- `vision.py` — Gemini 2.0 Flash, image → structured JSON
- `read_file.py` — file reader with paging
- `ask_user.py` — human-in-the-loop input
- `lasr/` — LASR optimization (evaluation, evolution, pareto, population, sampling)

**Agents** (`agents/`) — all LLM invocations via `invoke()`:
- `runner.py` — core LLM loop engine (`invoke()`, `run_agent()`, `SubagentConfig`, `ToolExecutor`)
- `think.py` — single-pass Claude + extended thinking (summaries, compaction, LASR prompts)
- `explore.py` — tool-use loop [Bash, Vision], max 10 iter
- `statistics.py` — tool-use loop [Bash, Vision], max 15 iter
- `codegen.py` — generate→run→fix loop for Plotly scripts
- `code.py` — single-pass code writer (feature/plot functions)

**Workflows** (`workflows/`) — Python async sequences composing tools + agents:
- `explore_dataset`, `ingest_documents`, `optimize_pattern`
- `teach_session`, `review_results`, `apply_rules`

**Orchestrator** (`orchestrator/loop.py`) — the outer LLM agent loop with all tool schemas.

---

## Context management (like Claude Code)
- `project_instructions.md` per project — static, like CLAUDE.md
- `project_summary.md` per project — agent-maintained by Think after milestones
- `sessions/session_{id}.json` — conversation turns, one per session
- Auto-compact via Think when context > 40k tokens
- In-context scratchpad (TodoWrite equivalent) maintained by orchestrator
- `context_carry` dict passes facts between agent steps

---

## Memory backend
- Default: `FileMemoryBackend` — reads/writes `project_summary.md`
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
- Agents use [Bash, Vision] as tools — never other agents
- Workflows are plain Python async functions — no LLM at the workflow level
- Tool definitions live in `tools/` as Anthropic JSON schema dicts
- System prompts live in `agents/prompts/*.md`
- `config.py` is the single source of truth for model IDs, token budgets, and paths
