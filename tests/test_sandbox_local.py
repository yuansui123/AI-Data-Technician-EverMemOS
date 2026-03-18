from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from sandbox.local_executor import LocalSandboxExecutor
from sandbox.policy import SandboxRuntimePolicy
from tools.bash import bash


class LocalSandboxLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_start_exec_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            executor = LocalSandboxExecutor(
                SandboxRuntimePolicy(backend="local", command_timeout_seconds=20)
            )
            session = await executor.start_session(
                project_dir=project_dir,
                scope="turn",
                allowed_roots=[project_dir],
            )

            try:
                cmd = f'"{sys.executable}" -c "print(\'first\')"'
                first = await session.exec(cmd, cwd=project_dir)
                second = await session.exec(cmd, cwd=project_dir)
            finally:
                await session.close()

            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(first.stdout, "first")
            self.assertEqual(second.stdout, "first")
            self.assertTrue(session.tmp_dir.exists())

    async def test_bash_result_shape_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            executor = LocalSandboxExecutor(
                SandboxRuntimePolicy(backend="local", command_timeout_seconds=20)
            )
            session = await executor.start_session(
                project_dir=project_dir,
                scope="task",
                allowed_roots=[project_dir],
            )

            cmd = f'"{sys.executable}" -c "print(\'shape\')"'
            legacy = await bash(cmd, cwd=project_dir, allowed_roots=[project_dir])
            session_result = await session.exec(cmd, cwd=project_dir)
            await session.close()

            self.assertEqual(set(legacy.__dict__.keys()), set(session_result.__dict__.keys()))
            self.assertEqual(session_result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
