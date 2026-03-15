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
# Tools import their schemas from tools/; agent schemas are inline.

from tools import TOOL_SCHEMAS

# Agent schemas (LLM reasoning loops available to orchestrator)
_AGENT_SCHEMAS = [
    {
        "name": "task",
        "description": (
            "Spawn a tool-use subagent for multi-step work. The agent gets a fresh context "
            "with bash, vision, read, and write tools. Write a detailed task description "
            "including ALL context the agent needs (file paths, data format, what to look for, "
            "constraints). Use for: data exploration, statistical analysis, code generation, "
            "evaluation, any multi-step investigation or modification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Detailed task description with all context the agent needs",
                },
            },
            "required": ["task"],
        },
    },
]

# Combine all: tools + agents
ORCHESTRATOR_TOOLS = [
    *TOOL_SCHEMAS,
    *_AGENT_SCHEMAS,
]


# ── Matplotlib preamble & epilogue (injected into plot tool code) ─────────────

_MPL_PREAMBLE = """\
import matplotlib as _mpl
_mpl.use('Agg')
import matplotlib.pyplot as _plt
_plt.style.use('dark_background')
_plt.rcParams.update({'figure.facecolor':'#0d1117','axes.facecolor':'#161b22',
    'text.color':'#e2e8f0','axes.labelcolor':'#e2e8f0',
    'xtick.color':'#e2e8f0','ytick.color':'#e2e8f0'})
"""

_MPL_EPILOGUE = """
try:
    import matplotlib.pyplot as _plt
    if _plt.get_fignums():
        import io as _io, base64 as _b64
        _buf = _io.BytesIO()
        _plt.savefig(_buf, format='png', dpi=150, bbox_inches='tight',
                     facecolor='#0d1117', edgecolor='none')
        _plt.close('all')
        _buf.seek(0)
        print('BASE64_PNG:' + _b64.b64encode(_buf.read()).decode())
except ImportError:
    pass
"""


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

        if tool_name == "read":
            from tools.read import read
            return read(
                path=inp["path"],
                max_chars=int(inp.get("max_chars", 8000)),
                offset_chars=int(inp.get("offset_chars", 0)),
            )

        if tool_name == "task":
            from agents.task import task
            # Inject project memory so the task agent doesn't re-explore
            memory_text = ""
            if self.memory_backend:
                try:
                    memory_text = await self.memory_backend.get_summary()
                except Exception:
                    pass
            desc = inp["task"]
            if memory_text:
                desc = f"## Project Context\n{memory_text}\n\n## Task\n{desc}"
            result_text = await task(
                task_description=desc,
                project_dir=p,
                on_event=self.on_event,
            )
            return {"response": result_text}

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
            # Log image paths as session artifacts
            if self.session:
                paths = []
                if inp.get("image_path"):
                    paths.append(inp["image_path"])
                for img in (inp.get("images") or []):
                    if img.get("path"):
                        paths.append(img["path"])
                for path_str in paths:
                    self.session.artifacts.append({
                        "turn": len(self.session.turns),
                        "tool": "vision",
                        "path": path_str,
                    })
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
            # Wrap with matplotlib dark-theme preamble + auto-capture epilogue
            full_code = _MPL_PREAMBLE + "\n" + code + "\n" + _MPL_EPILOGUE
            cmd = (
                f"$code = @'\n{full_code}\n'@\n"
                "$code | Out-File -Encoding utf8 C:\\Windows\\Temp\\show_plot.py\n"
                "python C:\\Windows\\Temp\\show_plot.py"
            )
            result = await bash(cmd, cwd=str(p))
            if not result.ok or not result.stdout.strip():
                return {"response": f"Plot failed: {result.stderr or '(no output)'}"}
            # Check for matplotlib base64 PNG output (scan from end)
            raw = result.stdout.strip()
            png_b64 = None
            for line in reversed(raw.split("\n")):
                if line.startswith("BASE64_PNG:"):
                    png_b64 = line[len("BASE64_PNG:"):]
                    break
            if png_b64:
                if self.on_event:
                    await self.on_event({
                        "type": "show_plot_image",
                        "image_base64": png_b64,
                        "title": title,
                    })
                return {"response": f"Plot '{title}' displayed in the browser (static image)."}
            # Otherwise expect Plotly JSON
            try:
                _json.loads(raw)
            except Exception as e:
                return {"response": f"Plot code did not produce valid JSON or matplotlib figure: {e}\n{raw[:300]}"}
            if self.on_event:
                await self.on_event({
                    "type": "show_plot",
                    "plot_json": raw,
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

def _load_system_prompt(project_dir: Path, memory: str, global_memory: str = "") -> str:
    prompt_path = Path(__file__).parent.parent / "prompts" / "system" / "orchestrator.md"
    base = prompt_path.read_text(encoding="utf-8")
    tmp_dir = project_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts = [base, f"\n## Current Session Paths\n- **Project directory:** `{project_dir}`\n- **Save all generated plots and output files to:** `{tmp_dir}`\n  (Never save to the source data directory.)"]
    if memory:
        parts.append(f"\n## Project Memory\n{memory}")
    if global_memory:
        parts.append(f"\n## Global Memory (across all projects)\n{global_memory}")
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
    from agents.runner import SubagentConfig, invoke
    import config

    project_dir = Path(project_dir)

    # Build context
    ctx = await build_context(project_dir, session, memory_backend, user_input)

    # Assemble conversation messages (include history for continuity)
    messages = []
    for turn in ctx.get("turns", []):
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role == "summary" and content:
            messages.append({"role": "user", "content": f"[Previous conversation summary]\n{content}"})
        elif role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_input})

    # System prompt = orchestrator.md + project memory + todos/carry
    system_prompt = _load_system_prompt(
        project_dir,
        memory=ctx.get("memory", ""),
        global_memory=ctx.get("global_memory", ""),
    )
    from session.context_builder import format_context_for_llm
    extra_context = format_context_for_llm(ctx)
    if extra_context:
        system_prompt += "\n\n" + extra_context

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

    # Periodic memory update (runs every ~15 turns)
    from orchestrator.memory_gate import maybe_update_memory
    await maybe_update_memory(session, memory_backend)

    # Passive EverMemOS conversation logging (if available)
    if hasattr(memory_backend, 'store_chat_turn'):
        await memory_backend.store_chat_turn("user", user_input)
        await memory_backend.store_chat_turn("assistant", result.text or "")

    return result.text or "(no response)"
