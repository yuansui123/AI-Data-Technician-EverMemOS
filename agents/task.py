"""Task agent — general-purpose multi-turn tool-use loop.

Replaces explore, statistics, codegen, code agents with a single
generic agent. The caller writes a detailed task description;
the agent executes using bash, vision, read, write tools.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sandbox.executor import SandboxExecutor


def _load_prompt() -> str:
    import sys
    import tempfile
    from tools.bash import runtime_shell_label

    p = Path(__file__).parent.parent / "prompts" / "system" / "task.md"
    runtime_shell = runtime_shell_label()
    runtime_context = (
        "\n\n## Runtime Environment\n"
        f"- OS platform: `{sys.platform}`\n"
        f"- bash tool shell: {runtime_shell}\n"
        f"- System temp directory: `{Path(tempfile.gettempdir())}`\n"
        "- Use commands and path syntax compatible with this runtime."
    )
    return p.read_text(encoding="utf-8") + runtime_context


async def task(
    task_description: str,
    project_dir: str | Path | None = None,
    max_iterations: int = 15,
    on_event=None,
    sandbox_executor: "SandboxExecutor | None" = None,
    parent_session_id: str | None = None,
) -> str:
    """Run the Task agent and return the response text.

    Args:
        task_description: Detailed task with all context baked in.
        project_dir: Working directory for tool execution.
        max_iterations: Max tool-use iterations (default 15).
        on_event: Callback for streaming events.
    """
    from agents.runner import SubagentConfig, ToolExecutor, invoke
    from sandbox import create_sandbox_executor
    from tools import TASK_TOOLS
    import config

    project_path = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
    active_sandbox_executor = sandbox_executor or create_sandbox_executor()
    sandbox_session = await active_sandbox_executor.start_session(
        project_dir=project_path,
        scope="task",
        parent_session_id=parent_session_id,
        allowed_roots=[project_path],
    )

    cfg = SubagentConfig(
        model=config.TASK_MODEL,
        system_prompt=_load_prompt(),
        tools=TASK_TOOLS,
        thinking_budget=0,
        max_iterations=max_iterations,
        max_tokens=4096,
    )

    sub_on_event = None
    if on_event:
        _TYPE_MAP = {"tool_call": "sub_tool_call", "tool_result": "sub_tool_result"}

        async def sub_on_event(event: dict):
            mapped = {**event, "subagent": "task"}
            mapped["type"] = _TYPE_MAP.get(event.get("type", ""), event["type"])
            await on_event(mapped)

    executor = ToolExecutor(
        project_dir=project_path,
        sandbox_session=sandbox_session,
        allowed_roots=[project_path],
    )

    try:
        result = await invoke(
            cfg,
            [{"role": "user", "content": task_description}],
            tool_executor=executor,
            on_event=sub_on_event,
        )
        return result.text.strip()
    finally:
        await sandbox_session.close()
