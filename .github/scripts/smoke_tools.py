from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.loop import OrchestratorToolExecutor
from tools.bash import bash, runtime_shell_label


async def _check_bash() -> None:
    result = await bash("echo adt_smoke")
    if not result.ok:
        raise RuntimeError(f"bash smoke failed: rc={result.returncode} stderr={result.stderr}")
    if "adt_smoke" not in result.stdout:
        raise RuntimeError(f"bash smoke failed: unexpected stdout={result.stdout!r}")


async def _check_plot() -> None:
    executor = OrchestratorToolExecutor(
        project_dir=Path(".").resolve(),
        memory_backend=None,
        context_carry={},
    )
    result = await executor.execute(
        "plot",
        {
            "python_code": (
                "import json\n"
                "fig = {\n"
                "  'data': [{'x': [0, 1], 'y': [0, 1], 'type': 'scatter'}],\n"
                "  'layout': {'title': 'ci-smoke'}\n"
                "}\n"
                "print(json.dumps(fig))\n"
            ),
            "title": "CI Smoke",
        },
    )
    if "displayed in the browser" not in result:
        raise RuntimeError(f"plot smoke failed: {result}")


async def main() -> None:
    print(f"runtime shell: {runtime_shell_label()}")
    await _check_bash()
    await _check_plot()
    print("os smoke checks passed")


if __name__ == "__main__":
    asyncio.run(main())
