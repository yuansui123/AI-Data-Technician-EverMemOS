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


# ── Orchestrator tool definitions (Anthropic JSON schema) ─────────────────────

ORCHESTRATOR_TOOLS = [
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
        "description": "Parse PDFs, CSVs or text files and extract metadata/content into project context.",
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
            "with label buttons (clean/artifact/noise/skip). Requires data_dir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_dir": {"type": "string", "description": "Path to data directory or specific .mat file"},
                "pattern": {"type": "string", "description": "Optional: pattern name to label for (e.g. 'artifact')"},
                "n_signals": {"type": "integer", "description": "How many signals to label in this session (default 10)"},
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
    {
        "name": "vision_analyze",
        "description": (
            "Send a single image to Gemini for visual analysis. Use when a plot or image already "
            "exists on disk and you want a description or pattern assessment. "
            "Returns: description, likely_pattern, rule_assessment, suggested_feature_gap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Absolute path to the PNG/JPG file."},
                "context": {
                    "type": "object",
                    "description": "Optional context: signal_id, known_patterns, current_rule, TP/FP/FN/TN counts.",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Execute a shell command via Windows PowerShell. "
            "For multi-line Python: write to a temp file using a here-string, then run it: "
            "$code = @'\\nimport numpy as np\\nprint(np.zeros(3))\\n'@; "
            "$code | Out-File -Encoding utf8 C:\\Windows\\Temp\\tmp.py; python C:\\Windows\\Temp\\tmp.py. "
            "Use Get-ChildItem or dir for listing. Select-Object -First N replaces head."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "cwd": {"type": "string", "description": "Optional working directory"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "ask_user",
        "description": "Ask the user a clarifying question and wait for their answer. Use only when genuinely blocked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"}
            },
            "required": ["question"],
        },
    },
    {
        "name": "todo_write",
        "description": (
            "Create or update the session todo list. "
            "Use to track multi-step plans and record what was actually done. "
            "IMPORTANT: You may only set status='done' or status='failed' when you provide "
            "at least one evidence item containing a real tool result. "
            "Never mark a todo done without evidence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Full replacement todo list for this session.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":     {"type": "string", "description": "Short unique id, e.g. 'a1f'"},
                            "title":  {"type": "string", "description": "Step description"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "running", "done", "failed"],
                            },
                            "evidence": {
                                "type": "array",
                                "description": "Proof this step completed. Required for done/failed.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type":   {"type": "string", "description": "bash|file|vision|text"},
                                        "name":   {"type": "string", "description": "Tool name or filename"},
                                        "result": {"type": "string", "description": "Key excerpt from result"},
                                    },
                                    "required": ["type", "name", "result"],
                                },
                            },
                        },
                        "required": ["id", "title", "status"],
                    },
                }
            },
            "required": ["todos"],
        },
    },
]


# ── Tool executor ──────────────────────────────────────────────────────────────

class OrchestratorToolExecutor:
    def __init__(self, project_dir: Path, memory_backend, context_carry: dict, session=None, on_event=None, answer_queue=None):
        self.project_dir = project_dir
        self.memory_backend = memory_backend
        self.carry = dict(context_carry)
        self.session = session  # held so todo_write can update session.todos in place
        self.on_event = on_event  # forwarded to workflows so subagent steps are visible
        self.answer_queue = answer_queue  # asyncio.Queue for web-mode ask_user answers

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
            )

        if tool_name == "review_results":
            from workflows.review_results import review_results
            return await review_results(p, self.memory_backend, inp.get("pattern"), self.carry)

        if tool_name == "apply_rules":
            from workflows.apply_rules import apply_rules
            return await apply_rules(p, self.memory_backend, inp.get("pattern"))

        if tool_name == "statistics":
            from subagents.reasoners.statistics import statistics
            return await statistics(
                task=inp["task"],
                pattern=inp.get("pattern"),
                feature_matrix_path=str(p / "cache" / "feature_matrix.parquet"),
                project_dir=p,
                context_carry=self.carry,
            )

        if tool_name == "explore":
            from subagents.reasoners.explore import explore
            return await explore(inp["data_dir"], inp["task"], p, self.carry,
                                 on_event=self.on_event)

        if tool_name == "vision_analyze":
            from subagents.primitives.vision import vision
            result = await vision(inp["image_path"], context=inp.get("context"))
            return result  # already a dict

        if tool_name == "bash":
            from subagents.primitives.bash import bash
            result = await bash(inp["command"], cwd=inp.get("cwd", str(p)))
            out = result.stdout or ""
            if result.stderr:
                out += f"\n[stderr] {result.stderr}"
            return {"stdout": out or "(no output)"}

        if tool_name == "ask_user":
            import asyncio
            question = inp["question"]
            if self.on_event:
                await self.on_event({"type": "ask_user", "question": question})
            if self.answer_queue is not None:
                # Web mode: wait for user to type answer in the chat input
                answer = await asyncio.wait_for(self.answer_queue.get(), timeout=600)
            else:
                # CLI fallback
                from orchestrator.tools import ask_user as _cli_ask_user
                answer = await _cli_ask_user(question)
            return {"user_answer": answer}

        if tool_name == "todo_write":
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

def _load_system_prompt(project_dir: Path, summary: str, instructions: str) -> str:
    prompt_path = Path(__file__).parent.parent / "subagents" / "prompts" / "orchestrator.md"
    base = prompt_path.read_text(encoding="utf-8")
    tmp_dir = project_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts = [base, f"\n## Current Session Paths\n- **Project directory:** `{project_dir}`\n- **Save all generated plots and output files to:** `{tmp_dir}`\n  (Never save to the source data directory.)"]
    if instructions:
        parts.append(f"\n## Project Instructions\n{instructions}")
    if summary:
        parts.append(f"\n## Project Summary (memory)\n{summary}")
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
    from subagents.base import SubagentConfig, invoke, ToolExecutor
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

    # System prompt = orchestrator.md + project context
    system_prompt = _load_system_prompt(
        project_dir,
        summary=ctx.get("summary", ""),
        instructions=ctx.get("instructions", ""),
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
