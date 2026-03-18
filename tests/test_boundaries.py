from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tools.bash import bash
from tools.read import read


class ReadBoundaryTests(unittest.TestCase):
    def test_read_allows_path_within_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp:
            root = Path(root_tmp)
            target = root / "allowed.txt"
            target.write_text("hello", encoding="utf-8")

            result = read(path=target, allowed_roots=[root])
            self.assertIn("hello", result["response"])

    def test_read_rejects_path_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as other_tmp:
            root = Path(root_tmp)
            other = Path(other_tmp) / "blocked.txt"
            other.write_text("blocked", encoding="utf-8")

            result = read(path=other, allowed_roots=[root])
            self.assertIn("outside allowed roots", result["response"])


class BashBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_bash_rejects_cwd_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as other_tmp:
            result = await bash(
                "pwd",
                cwd=other_tmp,
                allowed_roots=[root_tmp],
            )
            self.assertEqual(result.returncode, -1)
            self.assertIn("outside allowed roots", result.stderr)

    async def test_bash_allows_cwd_within_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp:
            cmd = f'"{sys.executable}" -c "print(\'ok\')"'
            result = await bash(cmd, cwd=root_tmp, allowed_roots=[root_tmp])
            self.assertEqual(result.returncode, 0)
            self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
