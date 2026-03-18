from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from sandbox.docker_executor import DockerSandboxExecutor
from sandbox.policy import SandboxRuntimePolicy

RUN_DOCKER_TESTS = os.getenv("RUN_DOCKER_SANDBOX_TESTS") == "1"


@unittest.skipUnless(RUN_DOCKER_TESTS, "Set RUN_DOCKER_SANDBOX_TESTS=1 to run Docker integration tests.")
class DockerSandboxIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_run_multiple_exec_and_teardown(self) -> None:
        with tempfile.TemporaryDirectory() as project_tmp:
            project_dir = Path(project_tmp)
            policy = SandboxRuntimePolicy(
                backend="docker",
                command_timeout_seconds=20,
                cpus="1",
                memory="1g",
                pids_limit=128,
                docker_image=os.getenv("SANDBOX_DOCKER_TEST_IMAGE", "python:3.11-slim"),
            )
            executor = DockerSandboxExecutor(policy=policy)
            session = await executor.start_session(
                project_dir=project_dir,
                scope="test",
                allowed_roots=[project_dir],
            )

            try:
                first = await session.exec("echo one", cwd=project_dir)
                second = await session.exec("echo two", cwd=project_dir)
            finally:
                container_name = session.container_name
                await session.close()

            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(first.stdout, "one")
            self.assertEqual(second.stdout, "two")

            proc = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name={container_name}",
                "--format",
                "{{.Names}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, _ = await proc.communicate()
            self.assertNotIn(container_name, stdout_b.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
