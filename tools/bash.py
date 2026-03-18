"""Bash tool — pure subprocess execution, no LLM.

The caller decides the command; this executes and returns stdout, stderr, returncode.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from sandbox.policy import resolve_and_validate_cwd

if TYPE_CHECKING:
    from sandbox.executor import SandboxSession


@dataclass
class BashResult:
    stdout: str
    stderr: str
    returncode: int
    new_artifact_paths: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def __str__(self) -> str:
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr] {self.stderr}")
        if self.returncode != 0:
            parts.append(f"[exit {self.returncode}]")
        return "\n".join(parts) or "(no output)"


async def bash(
    cmd: str,
    cwd: str | Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    sandbox_session: "SandboxSession | None" = None,
    allowed_roots: Sequence[str | Path] | None = None,
) -> BashResult:
    """Execute *cmd* in a subprocess and return a BashResult."""
    if sandbox_session is not None:
        return await sandbox_session.exec(
            cmd=cmd,
            cwd=cwd,
            timeout=timeout,
            env=env,
        )

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    resolved_cwd: Path | None = None
    if allowed_roots:
        roots = tuple(Path(root).resolve() for root in allowed_roots)
        default_cwd = Path(cwd).resolve() if cwd else roots[0]
        resolved_cwd, guard_error = resolve_and_validate_cwd(
            cwd=cwd,
            default_cwd=default_cwd,
            allowed_roots=roots,
        )
        if guard_error:
            return BashResult(stdout="", stderr=guard_error, returncode=-1)
    elif cwd:
        resolved_cwd = Path(cwd).resolve()

    proc: asyncio.subprocess.Process | None = None
    try:
        import sys as _sys
        if _sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd) if resolved_cwd else None,
                env=merged_env,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd) if resolved_cwd else None,
                env=merged_env,
            )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.communicate(), timeout=2)
            except Exception:
                pass
        return BashResult(stdout="", stderr=f"[timeout after {timeout}s]", returncode=-1)
    except Exception as exc:  # noqa: BLE001
        return BashResult(stdout="", stderr=str(exc), returncode=-1)

    return BashResult(
        stdout=stdout_b.decode(errors="replace").rstrip(),
        stderr=stderr_b.decode(errors="replace").rstrip(),
        returncode=proc.returncode or 0,
    )


def runtime_shell_label() -> str:
    """Human-readable shell label matching bash() runtime behavior."""
    import config
    import sys as _sys

    backend = str(getattr(config, "SANDBOX_BACKEND", "local")).lower()
    if backend == "docker":
        return "Docker sandbox shell (`docker exec sh -lc`)"
    if _sys.platform == "win32":
        return "Windows PowerShell (`powershell -Command`)"
    return "POSIX shell (`/bin/sh -c`)"


# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "bash",
    "description": (
        "Execute a shell command inside the active sandbox "
        "(local subprocess by default; Docker exec when docker backend is enabled). "
        "Use this to run Python scripts, list files, compute statistics, extract PDF text. "
        "Multi-line python -c is supported. Use single quotes inside python -c strings: "
        "python -c \"import sys; print('ok')\". "
        "Use command syntax that matches the current runtime environment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory. Defaults to project root."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Defaults to 60."},
        },
        "required": ["command"],
    },
}
