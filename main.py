"""AI Data Technician — entry point.

Usage:
    python main.py                          # new session, default project
    python main.py --web                    # web UI at http://localhost:8000
    python main.py --continue               # reload last session
    python main.py --session 20260312_1430  # load specific session
    python main.py --project MyProject      # use named project
    python main.py --start                  # init new project interactively
"""
from __future__ import annotations

import argparse
import asyncio
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
    p.add_argument("--continue", dest="resume", action="store_true",
                   help="Reload the most recent session")
    p.add_argument("--session", default=None, help="Load a specific session ID")
    p.add_argument("--start", action="store_true",
                   help="Initialise a new project interactively")
    p.add_argument("--web", action="store_true",
                   help="Start web UI at http://localhost:8000")
    p.add_argument("--port", type=int, default=8000, help="Web UI port (default: 8000)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Web mode — runs uvicorn directly (no asyncio.run needed)
    if args.web:
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
        return

    asyncio.run(_cli_main(args))


async def _cli_main(args) -> None:
    import config

    project_dir = Path(config.PROJECTS_DIR) / args.project
    project_dir.mkdir(parents=True, exist_ok=True)

    # Memory backend
    from memory.backend import get_memory_backend
    memory_backend = get_memory_backend(project_dir)

    # Project init wizard
    if args.start:
        from interface.cli import start_project
        await start_project(project_dir, memory_backend)

    # Session
    from session.session import Session

    if args.session:
        try:
            session = Session.load(project_dir, args.session)
            print(f"[Loaded session {args.session}]")
        except FileNotFoundError:
            print(f"Session {args.session!r} not found — starting new session.")
            session = Session(project_dir)
    elif args.resume:
        try:
            session = Session.load_latest(project_dir)
            print(f"[Resumed session {session.session_id}]")
        except FileNotFoundError:
            print("[No previous session found — starting new session.]")
            session = Session(project_dir)
    else:
        session = Session(project_dir)

    # REPL
    from interface.cli import repl
    await repl(project_dir, session, memory_backend)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
