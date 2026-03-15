"""Session — conversation turns, todos, context_carry, save/load.

Modeled on Claude Code's ~/.claude/projects/ session files.
One JSON file per session under projects/{Name}/sessions/session_{id}.json.
Todos also written to tmp/session_{id}/todos.json for persistence within session.

Todo schema:
    {
        "id":       str,          # short unique id, e.g. "a1f"
        "title":    str,          # human-readable step description
        "status":   "pending" | "running" | "done" | "failed",
        "evidence": [             # required when status == "done" or "failed"
            {"type": str, "name": str, "result": str}
        ]
    }
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class Session:
    def __init__(self, project_dir: str | Path, session_id: str | None = None):
        self.project_dir = Path(project_dir)
        self.session_id: str = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.turns: list[dict[str, str]] = []
        self.todos: list[dict[str, Any]] = []   # structured task list with evidence
        self.context_carry: dict[str, Any] = {}  # small fact-passing dict between steps
        self.last_memory_turn: int = 0           # turn count at last periodic memory update

    # ── turn management ───────────────────────────────────────────────────────

    def append(self, user_input: str, response: str) -> None:
        self.turns.append({"role": "user", "content": user_input})
        self.turns.append({"role": "assistant", "content": response})

    def replace_turns(self, turns: list[dict[str, str]]) -> None:
        """Replace turn list (used by auto-compact)."""
        self.turns = turns

    def oldest_turns(self, n: int) -> list[dict[str, str]]:
        return self.turns[:n]

    def recent_turns(self, n: int) -> list[dict[str, str]]:
        return self.turns[-n:]

    # ── persistence ───────────────────────────────────────────────────────────

    @property
    def _session_file(self) -> Path:
        return self.project_dir / "sessions" / f"session_{self.session_id}.json"

    @property
    def _todos_file(self) -> Path:
        return self.project_dir / "tmp" / f"session_{self.session_id}" / "todos.json"

    def save(self) -> None:
        # turns + context_carry
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self.session_id,
            "turns": self.turns,
            "context_carry": self.context_carry,
            "last_memory_turn": self.last_memory_turn,
        }
        self._session_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # todos
        self._todos_file.parent.mkdir(parents=True, exist_ok=True)
        self._todos_file.write_text(
            json.dumps({"todos": self.todos}, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, project_dir: str | Path, session_id: str) -> Session:
        project_path = Path(project_dir)
        session_file = project_path / "sessions" / f"session_{session_id}.json"
        data = json.loads(session_file.read_text(encoding="utf-8"))

        session = cls(project_dir, session_id)
        session.turns = data["turns"]
        session.context_carry = data.get("context_carry", {})
        session.last_memory_turn = data.get("last_memory_turn", 0)

        todos_file = project_path / "tmp" / f"session_{session_id}" / "todos.json"
        if todos_file.exists():
            session.todos = json.loads(
                todos_file.read_text(encoding="utf-8")
            ).get("todos", [])

        return session

    @classmethod
    def load_latest(cls, project_dir: str | Path) -> Session:
        sessions_dir = Path(project_dir) / "sessions"
        session_files = sorted(sessions_dir.glob("session_*.json"))
        if not session_files:
            raise FileNotFoundError(f"No sessions found in {sessions_dir}")
        session_id = session_files[-1].stem.removeprefix("session_")
        return cls.load(project_dir, session_id)

    # ── repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"Session(id={self.session_id!r}, "
            f"turns={len(self.turns)}, "
            f"project={self.project_dir.name!r})"
        )
