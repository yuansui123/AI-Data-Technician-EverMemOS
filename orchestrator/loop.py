"""Orchestrator main loop — true LLM agent loop (like Claude Code).

The orchestrator LLM sees the full context, calls tools, sees results,
and decides what to do next until it produces a final text response.

Entry point: run(user_input, session, project_dir, memory_backend) → str
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.backend import MemoryBackend
    from session.session import Session


# ── Orchestrator tool definitions ──────────────────────────────────────────────
# Tools import their schemas from tools/; workflow/agent schemas are inline.

from tools import TOOL_SCHEMAS

# Workflow schemas (no tool file — they dispatch to workflows/)
_WORKFLOW_SCHEMAS = [
    {
        "name": "explore_dataset",
        "description": "Explore a dataset directory: list files, profile signals, compute basic statistics. Use when user provides a data path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string", "description": "Absolute path to dataset folder or file"}
            },
            "required": ["data_dir"],
        },
    },
    {
        "name": "ingest_documents",
        "description": (
            "Read PDFs or text documents and synthesise their content into project_memory.md "
            "via the Think agent. Use for research papers, protocol descriptions, README files. "
            "NOT for .mat, .m, .py, or binary data files — use read for those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of absolute file paths to ingest",
                },
                "data_dir": {"type": "string", "description": "Optional: directory to scan for files"},
            },
            "required": [],
        },
    },
    {
        "name": "optimize_pattern",
        "description": "Run LASR optimization loop to find the best rule for a signal pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Name of the signal pattern to optimize"}
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "teach_session",
        "description": (
            "Interactive labelling session — shows signals one-by-one as popup modals "
            "with label buttons. Requires data_dir. "
            "ALWAYS use this when user wants to label, teach, or annotate signals. "
            "NEVER launch external GUI scripts — pass any style reference as view_description instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string", "description": "Path to data directory or specific .mat file"},
                "pattern": {"type": "string", "description": "Optional: pattern name to label for (e.g. 'artifact')"},
                "n_signals": {"type": "integer", "description": "How many signals to label in this session (default 10)"},
                "view_description": {
                    "type": "string",
                    "description": (
                        "Optional: free-text description of how signals should be displayed, "
                        "e.g. 'all channels stacked with 1000-unit offset', 'MTL channels only'. "
                        "If omitted the workflow will ask the user."
                    ),
                },
                "ref_file_path": {
                    "type": "string",
                    "description": (
                        "Optional: absolute path to a reference script (.py or .m) the user wants "
                        "the display to mimic. Pass this whenever the user says 'similar to <path>'. "
                        "Pass the raw file path here — do NOT embed it inside view_description."
                    ),
                },
                "plot_script": {
                    "type": "string",
                    "description": (
                        "Optional pre-built Python code for rendering each signal. "
                        "Variables `mat_path`, `ch_idx`, `tr_idx` are pre-defined. "
                        "Must end with `print(json.dumps(fig))`. "
                        "Leave unset — let view_description generate this automatically."
                    ),
                },
            },
            "required": ["data_dir"],
        },
    },
    {
        "name": "review_results",
        "description": "Review classification results and collect user feedback.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Optional: pattern to review"}
            },
            "required": [],
        },
    },
    {
        "name": "apply_rules",
        "description": "Apply current rules to all signals and write label outputs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Optional: pattern to apply rules for"}
            },
            "required": [],
        },
    },
]

# Agent schemas (LLM reasoning loops available to orchestrator)
_AGENT_SCHEMAS = [
    {
        "name": "statistics",
        "description": "Run quantitative analysis: feature distributions, group comparisons, correlation, model fitting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What statistical analysis to run"},
                "pattern": {"type": "string", "description": "Optional: signal pattern context"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "explore",
        "description": "Ad-hoc exploration using a Bash+Vision agent loop. Use for targeted questions about data structure, file contents, or multi-step signal inspection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string", "description": "Path to explore"},
                "task": {"type": "string", "description": "What to look for"},
            },
            "required": ["data_dir", "task"],
        },
    },
]

# Combine all: tools + agents + workflows
ORCHESTRATOR_TOOLS = [
    *TOOL_SCHEMAS,
    *_AGENT_SCHEMAS,
    *_WORKFLOW_SCHEMAS,
]


# ── Tool executor ──────────────────────────────────────────────────────────────

class OrchestratorToolExecutor:
    def __init__(self, project_dir: Path, memory_backend, context_carry: dict, session=None, on_event=None, answer_queue=None):
        self.project_dir = project_dir
        self.memory_backend = memory_backend
        self.carry = dict(context_carry)
        self.session = session  # held so todo_write can update session.todos in place
        self.on_event = on_event  # forwarded to workflows so subagent steps are visible
        self.answer_queue = answer_queue  # asyncio.Queue for ask_user answers from browser

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        try:
            result = await self._dispatch(tool_name, tool_input)
            if isinstance(result, dict):
                self.carry.update({k: v for k, v in result.items() if not k.startswith("_") and k != "response"})
                return result.get("response") or json.dumps(
                    {k: v for k, v in result.items() if k != "response"}, indent=2, default=str
                )
            return str(result)
        except Exception as exc:  # noqa: BLE001
            return f"[Error] {tool_name}: {exc}"

    async def _dispatch(self, tool_name: str, inp: dict) -> dict:
        p = self.project_dir

        if tool_name == "explore_dataset":
            from workflows.explore_dataset import explore_dataset
            return await explore_dataset(inp["data_dir"], p, self.memory_backend, self.carry,
                                         on_event=self.on_event)

        if tool_name == "ingest_documents":
            from workflows.ingest_documents import ingest_documents
            return await ingest_documents(
                inp.get("file_paths", []), p, self.memory_backend,
                inp.get("data_dir"), self.carry
            )

        if tool_name == "read":
            from tools.read import read
            return read(
                path=inp["path"],
                max_chars=int(inp.get("max_chars", 8000)),
                offset_chars=int(inp.get("offset_chars", 0)),
            )

        if tool_name == "optimize_pattern":
            from workflows.optimize_pattern import optimize_pattern
            return await optimize_pattern(inp["pattern"], p, self.memory_backend, self.carry)

        if tool_name == "teach_session":
            from workflows.teach_session import teach_session
            return await teach_session(
                p, self.memory_backend, inp.get("pattern"),
                data_dir=inp.get("data_dir"),
                n_signals=inp.get("n_signals", 10),
                on_event=self.on_event,
                answer_queue=self.answer_queue,
                plot_script=inp.get("plot_script"),
                view_description=inp.get("view_description"),
                ref_file_path=inp.get("ref_file_path"),
            )

        if tool_name == "review_results":
            from workflows.review_results import review_results
            return await review_results(p, self.memory_backend, inp.get("pattern"), self.carry)

        if tool_name == "apply_rules":
            from workflows.apply_rules import apply_rules
            return await apply_rules(p, self.memory_backend, inp.get("pattern"))

        if tool_name == "statistics":
            from agents.statistics import statistics
            return await statistics(
                task=inp["task"],
                pattern=inp.get("pattern"),
                feature_matrix_path=str(p / "cache" / "feature_matrix.parquet"),
                project_dir=p,
                context_carry=self.carry,
            )

        if tool_name == "explore":
            from agents.explore import explore
            return await explore(inp["data_dir"], inp["task"], p, self.carry,
                                 on_event=self.on_event)

        if tool_name == "write":
            from tools.write import write
            return write(
                path=inp["path"],
                content=inp["content"],
                project_dir=p,
            )

        if tool_name == "vision":
            from tools.vision import vision
            result = await vision(
                image_path=inp.get("image_path"),
                images=inp.get("images"),
                context=inp.get("context"),
            )
            return result  # already a dict

        if tool_name == "bash":
            from tools.bash import bash
            result = await bash(inp["command"], cwd=inp.get("cwd", str(p)))
            out = result.stdout or ""
            if result.stderr:
                out += f"\n[stderr] {result.stderr}"
            return {"stdout": out or "(no output)"}

        if tool_name == "plot":
            from tools.bash import bash
            import json as _json
            code = inp["python_code"]
            title = inp.get("title", "Plot")
            cmd = (
                f"$code = @'\n{code}\n'@\n"
                "$code | Out-File -Encoding utf8 C:\\Windows\\Temp\\show_plot.py\n"
                "python C:\\Windows\\Temp\\show_plot.py"
            )
            result = await bash(cmd, cwd=str(p))
            if not result.ok or not result.stdout.strip():
                return {"response": f"Plot failed: {result.stderr or '(no output)'}"}
            try:
                _json.loads(result.stdout.strip())
            except Exception as e:
                return {"response": f"Plot code did not produce valid JSON: {e}\n{result.stdout[:300]}"}
            if self.on_event:
                await self.on_event({
                    "type": "show_plot",
                    "plot_json": result.stdout.strip(),
                    "title": title,
                })
            return {"response": f"Plot '{title}' displayed in the browser."}

        if tool_name == "ask":
            import asyncio
            question = inp["question"]
            if self.on_event:
                await self.on_event({"type": "ask_user", "question": question})
            answer = await asyncio.wait_for(self.answer_queue.get(), timeout=600)
            return {"user_answer": answer}

        if tool_name == "todo":
            return self._todo_write(inp["todos"])

        raise ValueError(f"Unknown tool: {tool_name!r}")

    def _todo_write(self, todos: list) -> dict:
        """Validate and persist the todo list. Rejects done/failed items without evidence."""
        errors = []
        for item in todos:
            if item.get("status") in ("done", "failed"):
                if not item.get("evidence"):
                    errors.append(
                        f"Todo '{item['id']}' marked {item['status']} but has no evidence. "
                        "You must include at least one evidence item with a real tool result."
                    )
        if errors:
            return {"error": "\n".join(errors), "todos_saved": False}

        if self.session is not None:
            self.session.todos = todos
        return {"todos_saved": True, "count": len(todos)}


# ── Main entry point ───────────────────────────────────────────────────────────

def _load_system_prompt(project_dir: Path, memory: str) -> str:
    prompt_path = Path(__file__).parent.parent / "agents" / "prompts" / "orchestrator.md"
    base = prompt_path.read_text(encoding="utf-8")
    tmp_dir = project_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts = [base, f"\n## Current Session Paths\n- **Project directory:** `{project_dir}`\n- **Save all generated plots and output files to:** `{tmp_dir}`\n  (Never save to the source data directory.)"]
    if memory:
        parts.append(f"\n## Project Memory\n{memory}")
    return "\n".join(parts)


async def run(
    user_input: str,
    session: "Session",
    project_dir: str | Path,
    memory_backend: "MemoryBackend",
    on_event=None,
    answer_queue=None,
) -> str:
    from session.context_builder import build_context
    from agents.runner import SubagentConfig, invoke, ToolExecutor
    import config

    project_dir = Path(project_dir)

    # Build context
    ctx = await build_context(project_dir, session, memory_backend, user_input)

    # Assemble conversation messages (include history for continuity)
    messages = []
    for turn in ctx.get("turns", []):
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_input})

    # System prompt = orchestrator.md + project memory
    system_prompt = _load_system_prompt(
        project_dir,
        memory=ctx.get("memory", ""),
    )

    # Tool executor
    executor = OrchestratorToolExecutor(
        project_dir=project_dir,
        memory_backend=memory_backend,
        context_carry=dict(session.context_carry),
        session=session,
        on_event=on_event,
        answer_queue=answer_queue,
    )

    # Agent config
    iter_limit = config.ORCHESTRATOR_LIMITS.get("moderate", 20)
    cfg = SubagentConfig(
        model=config.ORCHESTRATOR_MODEL,
        system_prompt=system_prompt,
        tools=ORCHESTRATOR_TOOLS,
        thinking_budget=config.ORCHESTRATOR_THINKING_BUDGET,
        max_iterations=iter_limit,
        max_tokens=8192,
    )

    # Run agent loop
    result = await invoke(cfg, messages, tool_executor=executor, on_event=on_event)

    # Persist carry-over facts
    session.context_carry = executor.carry

    return result.text or "(no response)"
