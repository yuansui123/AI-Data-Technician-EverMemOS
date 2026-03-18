"""Sandbox execution interfaces and backend factory."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Sequence

from sandbox.policy import SandboxRuntimePolicy, validate_backend

if TYPE_CHECKING:
    from tools.bash import BashResult


class SandboxSession(Protocol):
    """Short-lived session that executes multiple commands in one sandbox."""

    session_id: str
    scope: str
    backend: str
    project_dir: Path
    tmp_dir: Path
    allowed_roots: tuple[Path, ...]

    async def exec(
        self,
        cmd: str,
        cwd: str | Path | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> "BashResult":
        ...

    async def close(self) -> None:
        ...


class SandboxExecutor(Protocol):
    """Factory for per-turn/per-task sandbox sessions."""

    backend: str
    policy: SandboxRuntimePolicy

    async def start_session(
        self,
        project_dir: str | Path,
        *,
        scope: str,
        parent_session_id: str | None = None,
        allowed_roots: Sequence[str | Path] | None = None,
    ) -> SandboxSession:
        ...


def make_policy_from_config() -> SandboxRuntimePolicy:
    import config

    backend = validate_backend(getattr(config, "SANDBOX_BACKEND", "local"))
    return SandboxRuntimePolicy(
        backend=backend,
        command_timeout_seconds=int(getattr(config, "SANDBOX_COMMAND_TIMEOUT_SECONDS", 120)),
        network_enabled=bool(getattr(config, "SANDBOX_NETWORK_ENABLED", False)),
        cpus=str(getattr(config, "SANDBOX_CPUS", "1")),
        memory=str(getattr(config, "SANDBOX_MEMORY", "2g")),
        pids_limit=int(getattr(config, "SANDBOX_PIDS_LIMIT", 256)),
        docker_image=str(getattr(config, "SANDBOX_DOCKER_IMAGE", "python:3.11-slim")),
    )


def create_sandbox_executor(policy: SandboxRuntimePolicy | None = None) -> SandboxExecutor:
    """Create the configured sandbox backend executor."""

    runtime_policy = policy or make_policy_from_config()
    backend = validate_backend(runtime_policy.backend)

    if backend == "local":
        from sandbox.local_executor import LocalSandboxExecutor

        return LocalSandboxExecutor(policy=runtime_policy)

    if backend == "docker":
        from sandbox.docker_executor import DockerSandboxExecutor

        return DockerSandboxExecutor(policy=runtime_policy)

    raise ValueError(f"Unsupported sandbox backend: {backend!r}")
