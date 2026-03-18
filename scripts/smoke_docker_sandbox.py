"""Smoke test: one Docker sandbox session with multiple commands."""
from __future__ import annotations

import asyncio
from pathlib import Path

from sandbox.docker_executor import DockerSandboxExecutor
from sandbox.policy import SandboxRuntimePolicy


async def main() -> int:
    root = Path(__file__).resolve().parent.parent
    project_dir = root / "projects" / "default"
    project_dir.mkdir(parents=True, exist_ok=True)

    policy = SandboxRuntimePolicy(
        backend="docker",
        command_timeout_seconds=30,
        cpus="1",
        memory="1g",
        pids_limit=128,
    )
    executor = DockerSandboxExecutor(policy)
    session = await executor.start_session(
        project_dir=project_dir,
        scope="smoke",
        allowed_roots=[project_dir],
    )

    try:
        first = await session.exec("echo sandbox-smoke-1", cwd=project_dir)
        second = await session.exec("echo sandbox-smoke-2", cwd=project_dir)

        print(f"session_id={session.session_id}")
        print(f"container={session.container_name}")
        print(f"cmd1 rc={first.returncode} out={first.stdout!r} err={first.stderr!r}")
        print(f"cmd2 rc={second.returncode} out={second.stdout!r} err={second.stderr!r}")

        if first.returncode != 0 or second.returncode != 0:
            return 1
        return 0
    finally:
        await session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
