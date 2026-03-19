"""Local subprocess sandbox backend (backward-compatible default)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sandbox.policy import (
    SandboxRuntimePolicy,
    build_session_id,
    build_session_tmp_dir,
    normalize_allowed_roots,
    resolve_and_validate_cwd,
)
from tools.bash import BashResult

_LOG = logging.getLogger("sandbox")


@dataclass
class LocalSandboxSession:
    """A local session that runs many subprocess commands in one logical sandbox."""

    session_id: str
    scope: str
    project_dir: Path
    tmp_dir: Path
    allowed_roots: tuple[Path, ...]
    policy: SandboxRuntimePolicy
    backend: str = "local"

    async def exec(
        self,
        cmd: str,
        cwd: str | Path | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> BashResult:
        start = time.monotonic()
        timeout_s = int(timeout or self.policy.command_timeout_seconds)
        resolved_cwd, guard_error = resolve_and_validate_cwd(
            cwd=cwd,
            default_cwd=self.project_dir,
            allowed_roots=self.allowed_roots,
        )
        if guard_error:
            duration_ms = int((time.monotonic() - start) * 1000)
            _LOG.info(
                "sandbox_exec backend=local session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
                self.session_id,
                self.scope,
                -1,
                duration_ms,
                cwd,
                cmd,
            )
            return BashResult(stdout="", stderr=guard_error, returncode=-1)

        _SENSITIVE_KEYS = {"ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "EVERMEMOS_API_KEY"}
        merged_env = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_KEYS}
        if env:
            merged_env.update(env)

        proc: asyncio.subprocess.Process | None = None
        try:
            import sys as _sys

            if _sys.platform == "win32":
                proc = await asyncio.create_subprocess_exec(
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(resolved_cwd),
                    env=merged_env,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(resolved_cwd),
                    env=merged_env,
                )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
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
            duration_ms = int((time.monotonic() - start) * 1000)
            _LOG.info(
                "sandbox_exec backend=local session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
                self.session_id,
                self.scope,
                -1,
                duration_ms,
                resolved_cwd,
                cmd,
            )
            return BashResult(stdout="", stderr=f"[timeout after {timeout_s}s]", returncode=-1)
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.monotonic() - start) * 1000)
            _LOG.info(
                "sandbox_exec backend=local session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
                self.session_id,
                self.scope,
                -1,
                duration_ms,
                resolved_cwd,
                cmd,
            )
            return BashResult(stdout="", stderr=str(exc), returncode=-1)

        result = BashResult(
            stdout=stdout_b.decode(errors="replace").rstrip(),
            stderr=stderr_b.decode(errors="replace").rstrip(),
            returncode=proc.returncode or 0,
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        _LOG.info(
            "sandbox_exec backend=local session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
            self.session_id,
            self.scope,
            result.returncode,
            duration_ms,
            resolved_cwd,
            cmd,
        )
        return result

    async def close(self) -> None:
        _LOG.info(
            "sandbox_session_closed backend=local session_id=%s scope=%s tmp_dir=%s",
            self.session_id,
            self.scope,
            self.tmp_dir,
        )


class LocalSandboxExecutor:
    """Executor that creates local subprocess-backed sandbox sessions."""

    def __init__(self, policy: SandboxRuntimePolicy):
        self.policy = policy
        self.backend = "local"

    async def start_session(
        self,
        project_dir: str | Path,
        *,
        scope: str,
        parent_session_id: str | None = None,
        allowed_roots: Sequence[str | Path] | None = None,
    ) -> LocalSandboxSession:
        project_path = Path(project_dir).resolve()
        roots = normalize_allowed_roots(project_path, allowed_roots)
        session_id = build_session_id(scope=scope, parent_session_id=parent_session_id)
        tmp_dir = build_session_tmp_dir(project_path, session_id)
        session = LocalSandboxSession(
            session_id=session_id,
            scope=scope,
            project_dir=project_path,
            tmp_dir=tmp_dir,
            allowed_roots=roots,
            policy=self.policy,
        )
        _LOG.info(
            "sandbox_session_started backend=local session_id=%s scope=%s project_dir=%s tmp_dir=%s",
            session.session_id,
            session.scope,
            session.project_dir,
            session.tmp_dir,
        )
        return session
