"""CodeGen agent — generate -> run -> fix loop for Plotly plot scripts.

Model:     claude-sonnet-4-6
Tools:     bash_execute, read_file, write_and_run
Max iter:  config.CODEGEN_MAX_ITER (default 8)
Output:    working Python script body (without the mat_path/ch_idx/tr_idx header)
"""
from __future__ import annotations

import re
from pathlib import Path


def _load_prompt() -> str:
    p = Path(__file__).parent / "prompts" / "codegen.md"
    return p.read_text(encoding="utf-8")


# -- Tool schemas for CodeGen ------------------------------------------------

BASH_TOOL: dict = {
    "name": "bash_execute",
    "description": (
        "Execute a shell command via Windows PowerShell. "
        "Use this to inspect .mat file structure, check array shapes, list directory contents, "
        "or run any exploratory Python snippet before writing the full plot script."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "cwd": {"type": "string", "description": "Working directory (optional)"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)"},
        },
        "required": ["command"],
    },
}

READ_FILE_TOOL: dict = {
    "name": "read_file",
    "description": (
        "Read any text file and return its contents. "
        "Use this to inspect reference scripts (.py, .m), config files, or any file you need to understand."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "max_chars": {"type": "integer", "description": "Max characters to return (default 8000)"},
        },
        "required": ["path"],
    },
}

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
                    "The Python script BODY -- do not include the header lines "
                    "(mat_path, ch_idx, tr_idx, import json). Those are prepended automatically."
                ),
            }
        },
        "required": ["code"],
    },
}


# -- Custom ToolExecutor -----------------------------------------------------

class CodeGenExecutor:
    """Executes write_and_run by safely writing code via base64 and running it."""

    def __init__(self, header: str, project_dir: str | None = None):
        self.header = header
        self.project_dir = project_dir
        self.last_successful_body: str | None = None

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "write_and_run":
            return await self._write_and_run(tool_input)
        if tool_name == "bash_execute":
            return await self._bash(tool_input)
        if tool_name == "read_file":
            return self._read_file(tool_input)
        return f"[CodeGenExecutor] Unknown tool: {tool_name}"

    async def _bash(self, inp: dict) -> str:
        from tools.bash import bash
        result = await bash(
            cmd=inp["command"],
            cwd=inp.get("cwd", self.project_dir),
            timeout=inp.get("timeout", 60),
        )
        out = result.stdout or ""
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        return out or "(no output)"

    def _read_file(self, inp: dict) -> str:
        path = Path(inp["path"])
        max_chars = int(inp.get("max_chars", 8000))
        if not path.exists():
            return f"File not found: {path}"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Could not read {path.name}: {e}"
        chunk = text[:max_chars]
        remaining = max(0, len(text) - max_chars)
        footer = f"\n[{remaining} more chars -- use offset_chars to page]" if remaining else ""
        return chunk + footer

    async def _write_and_run(self, inp: dict) -> str:
        import base64
        import json as _json
        from tools.bash import bash

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

        plot_out = stdout.split("STDERR:")[0].strip() if "STDERR:" in stdout else stdout.strip()
        stderr_out = stdout.split("STDERR:", 1)[1].strip() if "STDERR:" in stdout else ""

        if plot_out:
            try:
                parsed = _json.loads(plot_out)
                if "data" in parsed and "layout" in parsed:
                    self.last_successful_body = body
                    return f"SUCCESS: stdout is valid Plotly JSON ({len(plot_out)} chars)\n{plot_out[:200]}..."
                return f"stdout is JSON but missing 'data' or 'layout' keys: {list(parsed.keys())}"
            except _json.JSONDecodeError:
                pass

        if stderr_out:
            return f"FAILED:\n{stderr_out[:800]}"
        return "No output produced (missing print(json.dumps(fig))?)."


# -- Main entry point --------------------------------------------------------

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
    """Generate a working Plotly plot script via generate->run->fix loop.

    Returns the script BODY (without header), or None if all attempts failed.
    """
    from agents.runner import SubagentConfig, invoke
    import config as cfg

    mat_path = Path(mat_path)
    project_dir = Path(project_dir)

    # Build context
    summary = ""
    summary_path = project_dir / "project_summary.md"
    if summary_path.exists():
        summary = summary_path.read_text(encoding="utf-8")[:2000]

    ref_section = ""
    if ref_file_path:
        rp = Path(ref_file_path)
        if rp.exists():
            lang = "matlab" if rp.suffix == ".m" else "python"
            note = " (MATLAB -- translate visualization logic to Python/Plotly)" if lang == "matlab" else ""
            ref_section = (
                f"\n\n## Reference file: `{rp.name}`{note}\n```{lang}\n"
                f"{rp.read_text(errors='replace')[:6000]}\n```"
            )

    T, C, N = dims if dims else ("?", "?", "?")
    prior_section = (
        f"\n\n## Previous attempt (failed -- improve this):\n```python\n{prior_script}\n```"
        if prior_script else ""
    )

    header = "\n".join([
        "import json",
        f"mat_path = r'{mat_path}'",
        f"ch_idx = {ch_idx}",
        f"tr_idx = {tr_idx}",
    ])

    user_message = f"""Generate a working Python/Plotly signal plot script.

## Dataset context
{summary or "(no summary available)"}

## Sample .mat file
Path: `{mat_path}`
Shape: T={T} timepoints x C={C} channels x N={N} trials
h5py keys: `epoched_data` (TxCxN), `time` (T,), `new_elect_vals` (C,) -- electrode region codes{ref_section}{prior_section}

## Header already injected (do NOT repeat these lines in your code)
```python
{header}
```

## What the user wants
{description}

Write the script body, call write_and_run to test it, fix errors, and repeat until successful.
When done, output ONLY the final working script body."""

    sc = SubagentConfig(
        model=cfg.CODE_MODEL,
        system_prompt=_load_prompt(),
        tools=[BASH_TOOL, READ_FILE_TOOL, WRITE_AND_RUN_TOOL],
        thinking_budget=cfg.CODEGEN_THINKING_BUDGET,
        max_iterations=cfg.CODEGEN_MAX_ITER,
        max_tokens=8000,
    )

    executor = CodeGenExecutor(header=header, project_dir=str(project_dir))

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
    code = re.sub(r'^```\w*\s*', '', code)
    code = re.sub(r'\s*```$', '', code)
    code = code.strip()

    if code:
        try:
            compile(code, "<codegen>", "exec")
            return code
        except SyntaxError:
            pass

    if executor.last_successful_body:
        try:
            compile(executor.last_successful_body, "<codegen_fallback>", "exec")
            return executor.last_successful_body
        except SyntaxError:
            pass

    return None
