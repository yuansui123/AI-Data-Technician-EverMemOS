"""CodeGen reasoner — generate → run → fix loop for Plotly plot scripts.

Model:     claude-sonnet-4-6
Tool:      write_and_run  (writes code via base64, runs it, returns stdout+stderr)
Max iter:  config.CODEGEN_MAX_ITER  (default 4)
Output:    working Python script body (without the mat_path/ch_idx/tr_idx header)
"""
from __future__ import annotations

import re
from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent.parent / "prompts" / "codegen.md"
    return p.read_text(encoding="utf-8")


# ── write_and_run tool definition ─────────────────────────────────────────────

WRITE_AND_RUN_TOOL: dict = {
    "name": "write_and_run",
    "description": (
        "Write Python code to a temp file and execute it. "
        "The header (mat_path, ch_idx, tr_idx, import json) is automatically prepended. "
        "Returns stdout and stderr. Success = stdout contains valid Plotly JSON."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "The Python script BODY — do not include the header lines "
                    "(mat_path, ch_idx, tr_idx, import json). Those are prepended automatically."
                ),
            }
        },
        "required": ["code"],
    },
}


# ── Custom ToolExecutor ────────────────────────────────────────────────────────

class CodeGenExecutor:
    """Executes write_and_run by safely writing code via base64 and running it."""

    def __init__(self, header: str, project_dir: str | None = None):
        self.header = header
        self.project_dir = project_dir

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        if tool_name != "write_and_run":
            return f"[CodeGenExecutor] Unknown tool: {tool_name}"
        return await self._write_and_run(tool_input)

    async def _write_and_run(self, inp: dict) -> str:
        import base64
        import json as _json
        from subagents.primitives.bash import bash

        body = inp.get("code", "")
        full_code = self.header + "\n" + body
        encoded = base64.b64encode(full_code.encode("utf-8")).decode("ascii")

        cmd = (
            f"python -c \"import base64,pathlib; "
            f"pathlib.Path('C:/Windows/Temp/codegen_plot.py')"
            f".write_bytes(base64.b64decode('{encoded}'))\"\n"
            "python C:/Windows/Temp/codegen_plot.py "
            "2>C:/Windows/Temp/codegen_err.txt; "
            "$ec=$LASTEXITCODE; "
            "$err=if(Test-Path C:/Windows/Temp/codegen_err.txt)"
            "{Get-Content C:/Windows/Temp/codegen_err.txt -Raw}else{''}; "
            "if($err){Write-Host 'STDERR:' -NoNewline; Write-Host $err -NoNewline}"
        )
        result = await bash(cmd, cwd=self.project_dir, timeout=30)
        stdout = result.stdout or ""

        # Validate if stdout looks like Plotly JSON
        plot_out = stdout.split("STDERR:")[0].strip() if "STDERR:" in stdout else stdout.strip()
        stderr_out = stdout.split("STDERR:", 1)[1].strip() if "STDERR:" in stdout else ""

        if plot_out:
            try:
                parsed = _json.loads(plot_out)
                if "data" in parsed and "layout" in parsed:
                    return f"SUCCESS: stdout is valid Plotly JSON ({len(plot_out)} chars)\n{plot_out[:200]}..."
                return f"stdout is JSON but missing 'data' or 'layout' keys: {list(parsed.keys())}"
            except _json.JSONDecodeError:
                pass

        if stderr_out:
            return f"FAILED:\n{stderr_out[:800]}"
        return "No output produced (missing print(json.dumps(fig))?)."


# ── Main entry point ───────────────────────────────────────────────────────────

async def codegen(
    description: str,
    mat_path: str | Path,
    ch_idx: int,
    tr_idx: int,
    project_dir: str | Path,
    dims: tuple | None = None,
    ref_file_path: str | Path | None = None,
    prior_script: str | None = None,
    on_event=None,
) -> str | None:
    """Generate a working Plotly plot script via generate→run→fix loop.

    Returns the script BODY (without header), or None if all attempts failed.
    """
    from subagents.base import SubagentConfig, invoke
    import config as cfg

    mat_path = Path(mat_path)
    project_dir = Path(project_dir)

    # ── Build context ──────────────────────────────────────────────────────────
    summary = ""
    summary_path = project_dir / "project_summary.md"
    if summary_path.exists():
        summary = summary_path.read_text(encoding="utf-8")[:2000]

    ref_section = ""
    if ref_file_path:
        rp = Path(ref_file_path)
        if rp.exists():
            lang = "matlab" if rp.suffix == ".m" else "python"
            note = " (MATLAB — translate visualization logic to Python/Plotly)" if lang == "matlab" else ""
            ref_section = (
                f"\n\n## Reference file: `{rp.name}`{note}\n```{lang}\n"
                f"{rp.read_text(errors='replace')[:6000]}\n```"
            )

    T, C, N = dims if dims else ("?", "?", "?")
    prior_section = (
        f"\n\n## Previous attempt (failed — improve this):\n```python\n{prior_script}\n```"
        if prior_script else ""
    )

    # ── Script header (prepended to every write_and_run call) ─────────────────
    header = "\n".join([
        "import json",
        f"mat_path = r'{mat_path}'",
        f"ch_idx = {ch_idx}",
        f"tr_idx = {tr_idx}",
    ])

    # ── User message ───────────────────────────────────────────────────────────
    user_message = f"""Generate a working Python/Plotly signal plot script.

## Dataset context
{summary or "(no summary available)"}

## Sample .mat file
Path: `{mat_path}`
Shape: T={T} timepoints × C={C} channels × N={N} trials
h5py keys: `epoched_data` (T×C×N), `time` (T,), `new_elect_vals` (C,) — electrode region codes{ref_section}{prior_section}

## Header already injected (do NOT repeat these lines in your code)
```python
{header}
```

## What the user wants
{description}

Write the script body, call write_and_run to test it, fix errors, and repeat until successful.
When done, output ONLY the final working script body."""

    # ── Config and executor ────────────────────────────────────────────────────
    sc = SubagentConfig(
        model=cfg.CODE_MODEL,
        system_prompt=_load_prompt(),
        tools=[WRITE_AND_RUN_TOOL],
        thinking_budget=0,
        max_iterations=cfg.CODEGEN_MAX_ITER,
        max_tokens=4096,
    )

    executor = CodeGenExecutor(header=header, project_dir=str(project_dir))

    # Wrap events for activity log
    sub_on_event = None
    if on_event:
        async def sub_on_event(event: dict):
            if event["type"] == "tool_call":
                code_preview = (event["input"].get("code", "")[:80] + "...").replace("\n", " ")
                await on_event({"type": "sub_tool_call", "subagent": "codegen",
                                "tool": "write_and_run", "input": {"code": code_preview}})
            elif event["type"] == "tool_result":
                await on_event({"type": "sub_tool_result", "subagent": "codegen",
                                "tool": "write_and_run", "result": event["result"][:120]})

    result = await invoke(sc, [{"role": "user", "content": user_message}],
                          tool_executor=executor, on_event=sub_on_event)

    code = result.text.strip()
    # Strip accidental markdown fences
    code = re.sub(r'^```\w*\s*', '', code)
    code = re.sub(r'\s*```$', '', code)
    code = code.strip()

    if not code:
        return None

    # Syntax check
    try:
        compile(code, "<codegen>", "exec")
    except SyntaxError:
        return None

    return code
