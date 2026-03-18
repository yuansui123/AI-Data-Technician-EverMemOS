"""Docker sandbox backend: one container per session, many docker exec calls."""
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


def _container_name(session_id: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in session_id)
    return f"adt-sbx-{clean}"[:63]


@dataclass
class DockerSandboxSession:
    """A Docker-backed sandbox session."""

    session_id: str
    scope: str
    project_dir: Path
    tmp_dir: Path
    allowed_roots: tuple[Path, ...]
    policy: SandboxRuntimePolicy
    container_id: str
    container_name: str
    backend: str = "docker"

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
                "sandbox_exec backend=docker session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
                self.session_id,
                self.scope,
                -1,
                duration_ms,
                cwd,
                cmd,
            )
            return BashResult(stdout="", stderr=guard_error, returncode=-1)

        args = ["docker", "exec", "-i"]
        for k, v in (env or {}).items():
            args.extend(["-e", f"{k}={v}"])
        args.extend(["-w", str(resolved_cwd), self.container_name, "sh", "-lc", cmd])

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
                "sandbox_exec backend=docker session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
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
                "sandbox_exec backend=docker session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
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
            "sandbox_exec backend=docker session_id=%s scope=%s exit_code=%s duration_ms=%s cwd=%s command=%r",
            self.session_id,
            self.scope,
            result.returncode,
            duration_ms,
            resolved_cwd,
            cmd,
        )
        return result

    async def close(self) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            self.container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        _LOG.info(
            "sandbox_session_closed backend=docker session_id=%s scope=%s container=%s",
            self.session_id,
            self.scope,
            self.container_name,
        )


class DockerSandboxExecutor:
    """Executor that creates one Docker container per sandbox session."""

    def __init__(self, policy: SandboxRuntimePolicy):
        self.policy = policy
        self.backend = "docker"

    async def start_session(
        self,
        project_dir: str | Path,
        *,
        scope: str,
        parent_session_id: str | None = None,
        allowed_roots: Sequence[str | Path] | None = None,
    ) -> DockerSandboxSession:
        project_path = Path(project_dir).resolve()
        roots = normalize_allowed_roots(project_path, allowed_roots)
        session_id = build_session_id(scope=scope, parent_session_id=parent_session_id)
        tmp_dir = build_session_tmp_dir(project_path, session_id)

        if self.policy.network_enabled:
            raise ValueError("SANDBOX_NETWORK_ENABLED is not supported in v1; network must remain disabled.")

        name = _container_name(session_id)
        user_flag = "65532:65532"
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            user_flag = f"{os.getuid()}:{os.getgid()}"

        args = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            self.policy.cpus,
            "--memory",
            self.policy.memory,
            "--pids-limit",
            str(self.policy.pids_limit),
            "--user",
            user_flag,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=512m",
            "-v",
            f"{project_path}:{project_path}:ro",
            "-v",
            f"{tmp_dir}:{tmp_dir}:rw",
            "-w",
            str(project_path),
            self.policy.docker_image,
            "sh",
            "-lc",
            "while true; do sleep 3600; done",
        ]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        if proc.returncode != 0:
            err = stderr_b.decode(errors="replace").strip() or "docker run failed"
            raise RuntimeError(f"Failed to start docker sandbox session: {err}")

        container_id = stdout_b.decode(errors="replace").strip()
        session = DockerSandboxSession(
            session_id=session_id,
            scope=scope,
            project_dir=project_path,
            tmp_dir=tmp_dir,
            allowed_roots=roots,
            policy=self.policy,
            container_id=container_id,
            container_name=name,
        )

        _LOG.info(
            "sandbox_session_started backend=docker session_id=%s scope=%s container=%s project_dir=%s tmp_dir=%s",
            session.session_id,
            session.scope,
            session.container_name,
            session.project_dir,
            session.tmp_dir,
        )
        return session
