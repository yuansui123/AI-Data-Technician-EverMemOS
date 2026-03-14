# AI Data Technician — Architecture Plan

## Context

Synthesizing two existing approaches into a single local-first system:
- **v16CodeAct** (`C:\Users\yuans\Desktop\Mayo_dataset\agent_datacleaning\v16CodeAct`): Visualization agent, LangGraph 4-node loop. Hallucination root cause: unbounded 500-step context accumulation, no token ceiling, LLM-compliance-dependent termination.
- **v4cedars** (`C:\Users\yuans\Desktop\ClaudeCode\v4cedars`): Statistics/rules agent via Claude Code + 5 skills. LASR evolutionary rule optimization. Works well: interpretable boolean rules, project-scoped file state, human-in-the-loop GUI.

Goal: Local-first, single-user system modeled on Claude Code's context management. Three-tier subagent architecture. File-based memory now; EverMemOS pluggable later via abstraction layer.

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
Passes key outputs between subagent steps without each subagent seeing the full prior conversation:
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
    async def store(self, content: str, metadata: dict):
        update_markdown_section("project_summary.md", metadata["section"], content)
    async def get_summary(self) -> str:
        return read("project_summary.md")
    async def retrieve(self, query: str, top_k: int = 5) -> str:
        return self.get_summary()

class EverMemOSBackend(MemoryBackend):
    """Future upgrade. Plugged in via config."""
    # ... HTTP calls to localhost:1995/api/v1
```

**Config switch** (`config.py`):
```python
MEMORY_BACKEND = "file"        # now
# MEMORY_BACKEND = "evermemos" # future
```

---

## Subagent Taxonomy

### Orchestrator
- **Model**: claude-opus-4-6 + extended thinking (10k budget)
- **Role**: Main loop. Interprets user intent, maintains scratchpad, dispatches subagents/workflows, enforces iteration ceiling
- **Iteration limits**: simple=8, moderate=20, complex=50 (Plan agent sets complexity)

---

## Tier 1 — Primitives

### Bash
- **LLM**: None — pure subprocess
- Caller decides command; Bash executes and returns stdout + artifact paths
```python
async def bash(cmd: str, cwd: str = None, timeout: int = 60) -> BashResult:
    # returns: {stdout, stderr, returncode, new_artifact_paths}
```

### Vision
- **Model**: gemini-2.0-flash
- **Input**: image path (base64) + context (signal_id, known_patterns, current_rule, TP/FP/FN/TN)
- **Output**: `{description, likely_pattern, rule_assessment, suggested_feature_gap}`
- **Limit**: 1 Gemini call, no tools

### Code
- **Model**: claude-sonnet-4-6
- **Input**: feature_gap_description + 2-3 existing feature file snippets
- **Output**: writes to `tmp/code_drafts/` then moves to `lib/features/derived/` or `lib/plot/custom/`
- **Limit**: 1 API call, max 3 tool uses. Never executes.

---

## Tier 2 — Reasoners

### Plan — single-pass, extended thinking
```
Model:    claude-opus-4-6, thinking budget=8000
Tools:    none
Input:    project_summary + workflow_state snapshot + user request (pre-assembled)
Output:   {steps, complexity: "simple|moderate|complex", clarifications_needed, is_terminal}
Limit:    1 API call
```

### Think — single-pass, extended thinking
```
Model:    claude-sonnet-4-6, thinking budget=5000
Tools:    none
Input:    pre-processed results as text (Vision outputs, Bash outputs, feedback contents)
Output:   plain-language insight → memory_backend.store()
Limit:    1 API call
Also:     auto-compact (summarizes oldest conversation turns when context > 40k tokens)
```

### Explore — agentic tool-use loop
```
Model:    claude-sonnet-4-6, thinking budget=3000/iter
Tools:    [Bash, Vision]
Input:    paths to explore + task description
Behavior: adaptively decides what to look at next
          Bash: list files, load signals, compute stats, extract PDF text
          Vision: understand sample plots
Output:   {n_signals, fs, duration_s, file_types, quality_flags, domain_notes, suggested_patterns}
Limit:    max 10 tool-use iterations
```

### Statistics — agentic tool-use loop, general quantitative reasoning
```
Model:    claude-sonnet-4-6, thinking budget=3000/iter
Tools:    [Bash, Vision]
Input:    task + feature_matrix path + labeled signal IDs + pattern context
Behavior: chooses appropriate statistical approach for the question
Output:   {findings, best_rule?, fitness?, fp_signals, fn_signals, plateau?, suggested_feature_gap?}
Limit:    max 15 tool-use iterations
```

**Available approaches via Bash:**
- LASR (v4cedars `lib/optimization/`): rule optimization, mutation, crossover, pareto
- scipy/statsmodels: t-test, ANOVA, KS-test, distribution fitting, correlation
- sklearn: KMeans, DBSCAN, IsolationForest, PCA, UMAP
- ruptures: change point detection
- antropy/mne: entropy measures, EEG-specific analysis
- pandas/numpy: group statistics, feature distributions

---

## Tier 3 — Workflows (predefined Python async sequences)

```python
async def explore_dataset(data_dir, project_dir): ...
async def ingest_documents(file_paths, project_dir): ...
async def optimize_pattern(pattern_name, project_dir): ...
async def teach_session(project_dir): ...        # Bash blocks on GUI
async def review_results(project_dir): ...
async def apply_rules(project_dir): ...
```

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
│   ├── settings.local.json    ← full permissions (already created)
│   ├── PLAN.md                ← this file
│   └── CLAUDE.md              ← auto-loaded by Claude Code
│
├── main.py                    # CLI: python main.py [--continue] [--session ID]
├── config.py                  # API keys, model IDs, budgets, MEMORY_BACKEND="file"
├── requirements.txt
│
├── memory/
│   ├── backend.py             # MemoryBackend ABC + FileMemoryBackend
│   └── evermemos.py           # EverMemOSBackend (future)
│
├── session/
│   ├── session.py             # Session: turns, scratchpad, context_carry, save/load
│   └── context_builder.py    # assembles instructions+summary+turns+scratchpad
│
├── orchestrator/
│   ├── loop.py                # main async loop, tiered limits, auto-compact
│   ├── dispatcher.py          # routes action → subagent or workflow
│   └── tools.py               # ask_user()
│
├── subagents/
│   ├── base.py                # SubagentConfig, invoke() with tool-use loop
│   ├── primitives/
│   │   ├── bash.py
│   │   ├── vision.py          # Gemini
│   │   └── code.py
│   ├── reasoners/
│   │   ├── plan.py
│   │   ├── think.py           # also used for auto-compact
│   │   ├── explore.py
│   │   └── statistics.py
│   └── prompts/               # system prompt .md files
│       ├── orchestrator.md
│       ├── plan.md
│       ├── think.md
│       ├── explore.md
│       ├── statistics.md
│       └── code.md
│
├── workflows/
│   ├── explore_dataset.py
│   ├── ingest_documents.py
│   ├── optimize_pattern.py
│   ├── teach_session.py
│   ├── review_results.py
│   └── apply_rules.py
│
├── tools/                     # v4cedars lib → Anthropic tool JSON defs
│   ├── signal_tools.py
│   ├── feature_tools.py
│   ├── rule_tools.py
│   ├── plot_tools.py
│   └── optimization_tools.py
│
├── interface/
│   ├── cli.py                 # REPL with --continue / --session flags
│   └── server.py              # FastAPI (future)
│
└── tests/

─── External path imports ───────────────────────────────────────────────
C:\Users\yuans\Desktop\ClaudeCode\v4cedars\lib\
    feature_store.py, label_store.py, rules.py, workflow.py,
    optimization\*, features\*, plot\*, gui\*
```

---

## Code Reuse

### From v4cedars — import directly, no modification
- `lib/features/` — `@feature` / `@plot` registry + auto-discovery
- `lib/feature_store.py`, `lib/label_store.py`
- `lib/rules.py`, `lib/workflow.py`
- `lib/optimization/` — full LASR stack
- `lib/plot/`, `lib/gui/`
- Subagent prompts derived from `.claude/CLAUDE.md` and `.claude/skills/*/SKILL.md`

### From v16 — selective
- `plot_power_density_matrix_hilbert()` → adapt to `@plot` decorator → `lib/plot/custom/`
- LangGraph, DualRAG, 500-step loop → **not reused**

---

## Implementation Sequence

0. ✅ `.claude/settings.local.json` — full permissions
1. `config.py` + `memory/backend.py` + `session/session.py`
2. `session/context_builder.py`
3. `tools/` — v4cedars lib wrappers as Anthropic tool JSON defs
4. `subagents/primitives/` — bash.py, vision.py, code.py
5. `subagents/reasoners/statistics.py` — LASR + scipy/sklearn via Bash
6. `subagents/reasoners/explore.py`
7. `subagents/reasoners/plan.py`, `think.py`
8. `subagents/base.py` — unified invoke() with tool-use loop
9. `subagents/prompts/` — all system prompt markdown files
10. `workflows/` — all 6 async workflow functions
11. `orchestrator/` — loop, dispatcher, tools
12. `interface/cli.py` + `main.py`
13. Integration test

---

## Verification

1. `python main.py` → new session, loads project_instructions.md + project_summary.md
2. "I have EEG data at C:/data/, here is the paper [PDF]" → ingest_documents → explore_dataset → Think updates project_summary.md
3. "optimize muscle_artifact" → Plan (complexity=complex) → Statistics → plateau → Vision×N → Think → Code → Bash → Statistics → Think updates summary
4. `python main.py` next day → project_summary.md loaded, agent resumes with full context
5. `python main.py --continue` → last session turns reloaded
6. "is gamma_power significantly different between classes?" → Statistics (scipy t-test) → p-value reported
7. Context > 40k tokens → auto-compact triggers → Think summarizes → context shrinks
8. `MEMORY_BACKEND = "evermemos"` in config → EverMemOS backend active
