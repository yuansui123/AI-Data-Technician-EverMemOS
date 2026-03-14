# AI Data Technician

## What this project is
A local-first AI agent system for analyzing raw time series data (EEG/neural signals). Synthesizes two prior approaches into a three-tier subagent architecture modeled on Claude Code's context management.

**Read the full architecture plan before doing anything**: `.claude/PLAN.md`

---

## Key external dependencies (path imports — do not copy)
```
C:\Users\yuans\Desktop\ClaudeCode\v4cedars\lib\
    feature_store.py, label_store.py, rules.py, workflow.py
    optimization\*, features\*, plot\*, gui\*
```
All imports from v4cedars use this path. Never duplicate these files here.

---

## Three-tier subagent architecture

**Tier 1 — Primitives** (atomic, no reasoning loop):
- `Bash` — subprocess execution, no LLM
- `Vision` — Gemini 2.0 Flash, single image → text
- `Code` — claude-sonnet-4-6, writes files only, never executes

**Tier 2 — Reasoners** (bounded reasoning loops):
- `Plan` — claude-opus-4-6 + extended thinking 8k, single-pass, no tools
- `Think` — claude-sonnet-4-6 + extended thinking 5k, single-pass, no tools
- `Explore` — claude-sonnet-4-6, tool-use loop [Bash, Vision], max 10 iter
- `Statistics` — claude-sonnet-4-6, tool-use loop [Bash, Vision], max 15 iter

**Tier 3 — Workflows** (predefined Python async sequences in `workflows/`):
- `explore_dataset`, `ingest_documents`, `optimize_pattern`
- `teach_session`, `review_results`, `apply_rules`

---

## Context management (like Claude Code)
- `project_instructions.md` per project — static, like CLAUDE.md
- `project_summary.md` per project — agent-maintained by Think after milestones
- `sessions/session_{id}.json` — conversation turns, one per session
- Auto-compact via Think when context > 40k tokens
- In-context scratchpad (TodoWrite equivalent) maintained by orchestrator
- `context_carry` dict passes facts between subagent steps

---

## Memory backend
- Default: `FileMemoryBackend` — reads/writes `project_summary.md`
- Future: `EverMemOSBackend` at `localhost:1995/api/v1` — swap via `MEMORY_BACKEND` in `config.py`
- Orchestrator only calls `memory_backend.store()` / `memory_backend.get_summary()`

---

## Hallucination prevention (vs v16CodeAct's 500-step loop)
- Each subagent gets a **fresh bounded context** assembled by orchestrator
- Hard iteration limits at every level (Orchestrator: 8/20/50 by complexity, Explore: 10, Statistics: 15)
- Extended thinking replaces long reasoning chains within a single call
- Think agent post-processes results into compact summaries before entering orchestrator context
- Termination enforced at infrastructure level, not by LLM self-termination

---

## Coding conventions
- All subagent calls go through `subagents/base.py:invoke()`
- Primitives never call other subagents
- Reasoners use [Bash, Vision] as tools — never Code or other reasoners
- Workflows are plain Python async functions — no LLM at the workflow level
- Write tool definitions in `tools/` as Anthropic JSON schema dicts
- System prompts live in `subagents/prompts/*.md` — derive from v4cedars CLAUDE.md and SKILL.md files
- `config.py` is the single source of truth for model IDs, token budgets, and paths
