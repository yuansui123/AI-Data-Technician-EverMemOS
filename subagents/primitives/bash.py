"""Bash primitive — pure subprocess, no LLM.

The caller decides the command; Bash executes and returns stdout, stderr,
returncode, and any new file paths created under the project tmp dir.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path


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
) -> BashResult:
    """Execute *cmd* in a subprocess and return a BashResult."""
    import config

    # Inject v4cedars lib onto PYTHONPATH so callers can import it directly
    merged_env = os.environ.copy()
    merged_env["PYTHONPATH"] = (
        str(config.V4CEDARS_LIB)
        + os.pathsep
        + merged_env.get("PYTHONPATH", "")
    )
    if env:
        merged_env.update(env)

    try:
        import sys as _sys
        if _sys.platform == "win32":
            # PowerShell handles multi-line strings and Python -c correctly.
            # cmd.exe splits on newlines, breaking multi-line python -c commands.
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=merged_env,
            )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return BashResult(stdout="", stderr=f"[timeout after {timeout}s]", returncode=-1)
    except Exception as exc:  # noqa: BLE001
        return BashResult(stdout="", stderr=str(exc), returncode=-1)

    return BashResult(
        stdout=stdout_b.decode(errors="replace").rstrip(),
        stderr=stderr_b.decode(errors="replace").rstrip(),
        returncode=proc.returncode or 0,
    )
