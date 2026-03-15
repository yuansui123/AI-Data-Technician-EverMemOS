"""AI Data Technician — entry point.

Usage:
    python main.py                          # web UI at http://localhost:8000
    python main.py --port 9000              # web UI on custom port
    python main.py --project MyProject      # use named project
    python main.py --start                  # init new project directory
    python main.py --debug                  # log all LLM I/O
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Fix Windows console encoding — allow emoji/unicode in responses
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI Data Technician")
    p.add_argument("--project", default="default", help="Project name under projects/")
    p.add_argument("--start", action="store_true",
                   help="Initialise a new project directory")
    p.add_argument("--port", type=int, default=8000, help="Web UI port (default: 8000)")
    p.add_argument("--debug", action="store_true",
                   help="Log all LLM inputs/outputs to logs/debug_<timestamp>.txt")
    return p.parse_args()


def _setup_debug_log(args) -> None:
    """If --debug, set AI_DT_DEBUG_LOG env var so agents/runner.py can find the path."""
    if not args.debug:
        return
    import os
    from datetime import datetime
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"debug_{ts}.txt"
    os.environ["AI_DT_DEBUG_LOG"] = str(log_path)
    print(f"[debug] LLM log → {log_path}")


def _init_project(project_dir: Path) -> None:
    """Create project directory with an empty project_memory.md."""
    memory_path = project_dir / "project_memory.md"
    if memory_path.exists():
        print(f"project_memory.md already exists at {memory_path}")
        return
    project_dir.mkdir(parents=True, exist_ok=True)
    memory_path.write_text("# Project Memory\n", encoding="utf-8")
    print(f"Created {memory_path}")


def main() -> None:
    args = parse_args()
    _setup_debug_log(args)

    import config
    project_dir = Path(config.PROJECTS_DIR) / args.project

    if args.start:
        _init_project(project_dir)
        return

    import uvicorn
    print(f"Starting web UI at http://localhost:{args.port}")
    print("Open that URL in your browser. Ctrl-C to stop.")
    uvicorn.run(
        "interface.web:app",
        host="0.0.0.0",
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
