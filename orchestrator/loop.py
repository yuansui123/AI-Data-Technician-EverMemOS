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
    from sandbox.executor import SandboxExecutor, SandboxSession


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
    def __init__(
        self,
        project_dir: Path,
        memory_backend,
        context_carry: dict,
        session=None,
        on_event=None,
        answer_queue=None,
        sandbox_session: "SandboxSession | None" = None,
        sandbox_executor: "SandboxExecutor | None" = None,
    ):
        self.project_dir = project_dir
        self.memory_backend = memory_backend
        self.carry = dict(context_carry)
        self.session = session  # held so todo_write can update session.todos in place
        self.on_event = on_event  # forwarded to workflows so subagent steps are visible
        self.answer_queue = answer_queue  # asyncio.Queue for ask_user answers from browser
        self.sandbox_session = sandbox_session
        self.sandbox_executor = sandbox_executor

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

    @property
    def _allowed_roots(self) -> tuple[str, ...]:
        if self.sandbox_session is not None:
            return tuple(str(root) for root in self.sandbox_session.allowed_roots)
        return (str(self.project_dir),)

    async def _dispatch(self, tool_name: str, inp: dict) -> dict:
        p = self.project_dir

        if tool_name == "read":
            from tools.read import read
            return read(
                path=inp["path"],
                max_chars=int(inp.get("max_chars", 8000)),
                offset_chars=int(inp.get("offset_chars", 0)),
                allowed_roots=self._allowed_roots,
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
                sandbox_executor=self.sandbox_executor,
                parent_session_id=self.sandbox_session.session_id if self.sandbox_session else None,
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
            result = await bash(
                inp["command"],
                cwd=inp.get("cwd", str(p)),
                timeout=int(inp.get("timeout", 60)),
                sandbox_session=self.sandbox_session,
                allowed_roots=self._allowed_roots,
            )
            out = result.stdout or ""
            if result.stderr:
                out += f"\n[stderr] {result.stderr}"
            return {"stdout": out or "(no output)"}

        if tool_name == "plot":
            from tools.bash import bash
            import json as _json
            import shutil
            import sys
            from uuid import uuid4
            code = inp["python_code"]
            title = inp.get("title", "Plot")
            # Wrap with matplotlib dark-theme preamble + auto-capture epilogue
            full_code = _MPL_PREAMBLE + "\n" + code + "\n" + _MPL_EPILOGUE
            session_tmp = self.sandbox_session.tmp_dir if self.sandbox_session else (p / "tmp" / "session_plot_fallback")
            session_tmp.mkdir(parents=True, exist_ok=True)
            plot_script = session_tmp / f"adt_plot_{uuid4().hex}.py"
            try:
                plot_script.write_text(full_code, encoding="utf-8")
            except Exception as e:
                return {"response": f"Plot failed: could not write temp script: {e}"}

            mplconfig_dir: Path | None = None
            try:
                mplconfig_dir = session_tmp / f"adt_mplconfig_{uuid4().hex}"
                mplconfig_dir.mkdir(parents=True, exist_ok=True)
                cmd = f'"{sys.executable}" "{plot_script}"'
                result = await bash(
                    cmd,
                    cwd=str(p),
                    env={"MPLCONFIGDIR": str(mplconfig_dir)},
                    sandbox_session=self.sandbox_session,
                    allowed_roots=self._allowed_roots,
                )
            finally:
                try:
                    plot_script.unlink(missing_ok=True)
                except Exception:
                    pass
                if mplconfig_dir is not None:
                    try:
                        shutil.rmtree(mplconfig_dir, ignore_errors=True)
                    except Exception:
                        pass
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

        if tool_name == "recall":
            return await self._recall(inp)

        if tool_name == "remember":
            return await self._remember(inp)

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

    async def _recall(self, inp: dict) -> dict:
        """Recall tool — search L2 project + L3 global memory, synthesize via Think.

        Three phases:
          1. Retrieve from both project and global backends
          2. Emit UI event with queries + results
          3. Synthesize with Think agent (preserving project/global distinction)
        """
        from memory.backend import get_global_backend

        objective = inp["objective"]
        queries = inp.get("queries", [])[:3]
        top_k = inp.get("top_k", 8)

        all_results: list[dict] = []

        # ── Phase 1: Retrieve from both memory layers ─────────────────────
        global_backend = get_global_backend()

        for query in queries:
            # L2 project memory
            if hasattr(self.memory_backend, "retrieve_detailed"):
                project_hits = await self.memory_backend.retrieve_detailed(query, top_k=top_k)
                for hit in project_hits:
                    hit["source"] = "project"
                    all_results.append(hit)
            else:
                # FileMemoryBackend fallback
                summary = await self.memory_backend.get_summary()
                if summary:
                    all_results.append({
                        "content": summary, "memory_type": "summary",
                        "keywords": [], "timestamp": "", "group_id": "",
                        "user_id": "", "source": "project",
                    })

            # L3 global memory
            if hasattr(global_backend, "retrieve_detailed"):
                global_hits = await global_backend.retrieve_detailed(query, top_k=top_k)
                for hit in global_hits:
                    hit["source"] = "global"
                    all_results.append(hit)
            else:
                summary = await global_backend.get_summary()
                if summary:
                    all_results.append({
                        "content": summary, "memory_type": "summary",
                        "keywords": [], "timestamp": "", "group_id": "",
                        "user_id": "", "source": "global",
                    })

        # Deduplicate by content
        seen = set()
        unique_results = []
        for r in all_results:
            key = r["content"][:200]
            if key not in seen:
                seen.add(key)
                unique_results.append(r)
        all_results = unique_results

        # ── Phase 2: Emit UI event with full details ──────────────────────
        if self.on_event:
            await self.on_event({
                "type": "recall",
                "objective": objective,
                "queries": queries,
                "results": all_results,
                "result_count": len(all_results),
            })

        # ── Phase 3: Synthesize via Think agent ───────────────────────────
        if not all_results:
            return {"response": "No relevant memories found. Proceeding without recalled knowledge."}

        # Group results by source for Think
        project_lines = []
        global_lines = []
        for r in all_results:
            ts = r.get("timestamp", "")[:10]
            mtype = r.get("memory_type", "unknown")
            kw_raw = r.get("keywords") or []
            if isinstance(kw_raw, str):
                kw_raw = [kw_raw]
            kw = ", ".join(kw_raw)
            line = f"- [{mtype}"
            if ts:
                line += f", {ts}"
            line += f"] {r['content']}"
            if kw:
                line += f"  [keywords: {kw}]"
            if r.get("source") == "global":
                global_lines.append(line)
            else:
                project_lines.append(line)

        grouped_text = ""
        if project_lines:
            grouped_text += "## Project Memory (this project)\n" + "\n".join(project_lines) + "\n\n"
        if global_lines:
            grouped_text += "## Global Memory (cross-project)\n" + "\n".join(global_lines) + "\n\n"

        prompt = (
            f"MODE: recall_synthesis\n\n"
            f"## Objective\n{objective}\n\n"
            f"## Retrieved Memories\n{grouped_text}"
        )

        from agents.think import think
        synthesis = await think(prompt, thinking_budget=2000)

        if synthesis.startswith("MODE: no_update"):
            return {"response": "Memories found but none were relevant to the objective."}

        return {"response": f"## Recalled Knowledge\n\n{synthesis}"}

    async def _remember(self, inp: dict) -> dict:
        """Remember tool — explicitly save user-specified knowledge to long-term memory.

        Stores to the active memory backend (project or global scope).
        If using HybridMemoryBackend, this automatically writes to both file and EverMemOS.
        """
        from memory.backend import get_global_backend

        content = inp["content"]
        tags = inp.get("tags", [])
        scope = inp.get("scope", "project")

        # Choose target backend
        if scope == "global":
            backend = get_global_backend()
        else:
            backend = self.memory_backend

        # Build metadata
        section = "User Knowledge"
        if tags:
            # Use first tag as section hint for file backend
            section = tags[0].replace("_", " ").title()

        metadata = {
            "section": section,
            "role": "user",
            "memory_type": "episodic_memory",  # broadest EverMemOS type — covers all remembered knowledge
            "tags": tags,
        }

        # Store the memory
        try:
            await backend.store(content, metadata)
        except Exception as exc:
            return {"response": f"Failed to save memory: {exc}"}

        # Emit UI event so the browser shows confirmation
        if self.on_event:
            await self.on_event({
                "type": "remember",
                "content": content[:200],
                "tags": tags,
                "scope": scope,
            })

        tag_str = ", ".join(tags) if tags else "none"
        return {
            "response": (
                f"Saved to {scope} memory.\n"
                f"**Tags:** {tag_str}\n"
                f"**Content:** {content[:150]}{'...' if len(content) > 150 else ''}"
            )
        }


# ── Main entry point ───────────────────────────────────────────────────────────

def _load_system_prompt(project_dir: Path, memory: str, global_memory: str = "") -> str:
    import sys
    import tempfile
    from tools.bash import runtime_shell_label

    prompt_path = Path(__file__).parent.parent / "prompts" / "system" / "orchestrator.md"
    base = prompt_path.read_text(encoding="utf-8")
    tmp_dir = project_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    runtime_shell = runtime_shell_label()
    system_tmp_dir = Path(tempfile.gettempdir())
    parts = [
        base,
        (
            f"\n## Current Session Paths\n"
            f"- **Project directory:** `{project_dir}`\n"
            f"- **Save all generated plots and output files to:** `{tmp_dir}`\n"
            "  (Never save to the source data directory.)\n"
            f"- **Dataset directory:** `/data/datasets/`\n"
            "  (Contains pre-loaded datasets. List this directory to discover available data.)"
        ),
        (
            f"\n## Runtime Environment\n"
            f"- **OS platform:** `{sys.platform}`\n"
            f"- **bash tool shell:** {runtime_shell}\n"
            f"- **System temp directory:** `{system_tmp_dir}`\n"
            "- Use shell commands and path syntax compatible with this runtime."
        ),
    ]
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
    from sandbox import create_sandbox_executor
    import config

    project_dir = Path(project_dir).resolve()
    sandbox_executor = create_sandbox_executor()
    sandbox_session = await sandbox_executor.start_session(
        project_dir=project_dir,
        scope="turn",
        parent_session_id=session.session_id,
        allowed_roots=[project_dir, "/data/datasets"],
    )

    try:
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
            sandbox_session=sandbox_session,
            sandbox_executor=sandbox_executor,
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

        # Passive EverMemOS conversation logging (if available)
        if hasattr(memory_backend, 'store_chat_turn'):
            await memory_backend.store_chat_turn("user", user_input)
            await memory_backend.store_chat_turn("assistant", result.text or "")

        return result.text or "(no response)"
    finally:
        await sandbox_session.close()
