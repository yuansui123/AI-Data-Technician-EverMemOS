"""CLI REPL — interactive session with the AI Data Technician.

Usage:
    python main.py                     # new session
    python main.py --continue          # reload last session
    python main.py --session 20260312  # load specific session
    python main.py --project MyProject # use named project (default: "default")
    python main.py --start             # initialise a new project interactively
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def repl(
    project_dir: Path,
    session,
    memory_backend,
) -> None:
    """Async REPL loop. Exits on Ctrl-C / Ctrl-D / 'exit' / 'quit'."""
    from orchestrator.loop import run

    print(f"\n[AI Data Technician] Project: {project_dir.name}")
    print("Type your message, or 'exit' to quit.\n")

    while True:
        try:
            user_input = await _read_line()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        try:
            response = await run(
                user_input=user_input,
                session=session,
                project_dir=project_dir,
                memory_backend=memory_backend,
                on_event=_cli_event,
            )
        except Exception as exc:  # noqa: BLE001
            exc_type = type(exc).__name__
            msg = str(exc)
            if "529" in msg or "overloaded" in msg.lower():
                print("[API overloaded] Anthropic's servers are busy. Check status.claude.com and try again shortly.")
            elif "500" in msg or "internal server" in msg.lower():
                print("[API error] Anthropic returned a server error. Try again in a moment.")
            elif "rate" in msg.lower() or "429" in msg:
                print("[Rate limited] Too many requests. Wait a moment and try again.")
            else:
                print(f"[Error] {exc_type}: {msg}")
            continue

        print(f"\n{response}\n")
        session.append(user_input, response)
        session.save()


async def _cli_event(event: dict) -> None:
    """Print tool activity to terminal as it happens."""
    t = event.get("type")
    if t == "tool_call":
        tool = event["tool"]
        inp = event.get("input", {})
        # Show the most useful input field only
        hint = ""
        for key in ("data_dir", "task", "pattern", "command", "question", "file_paths"):
            if key in inp:
                val = str(inp[key])
                hint = f" {val[:60]}{'...' if len(val) > 60 else ''}"
                break
        print(f"  [tool] {tool}{hint}", flush=True)
    elif t == "tool_result":
        tool = event["tool"]
        result = event.get("result", "")
        lines = result.strip().splitlines()
        preview = lines[0][:80] if lines else ""
        print(f"  [done] {tool} -> {preview}", flush=True)


async def _read_line() -> str:
    loop = asyncio.get_event_loop()
    sys.stdout.write("> ")
    sys.stdout.flush()
    return (await loop.run_in_executor(None, sys.stdin.readline)).rstrip("\n")


async def start_project(project_dir: Path, memory_backend) -> None:
    """Interactive wizard to initialise project_instructions.md."""
    instructions_path = project_dir / "project_instructions.md"
    if instructions_path.exists():
        print(f"project_instructions.md already exists at {instructions_path}")
        return

    print("\n=== New Project Setup ===")
    fields = {
        "Dataset description": "",
        "Sampling rate (Hz)": "",
        "File format": "",
        "Task definition": "",
        "Signal categories / patterns of interest": "",
        "Known artifact types": "",
    }

    for key in fields:
        sys.stdout.write(f"{key}: ")
        sys.stdout.flush()
        fields[key] = sys.stdin.readline().strip()

    content = "# Project Instructions\n\n"
    for key, value in fields.items():
        content += f"## {key}\n{value}\n\n"

    project_dir.mkdir(parents=True, exist_ok=True)
    instructions_path.write_text(content, encoding="utf-8")
    print(f"\nCreated {instructions_path}")
