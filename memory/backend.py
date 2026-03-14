"""Memory abstraction layer.

Default: FileMemoryBackend — reads/writes project_summary.md.
Future:  EverMemOSBackend   — swap via MEMORY_BACKEND in config.py.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path


class MemoryBackend(ABC):
    @abstractmethod
    async def store(self, content: str, metadata: dict) -> None:
        """Persist a chunk of content (e.g. a milestone insight).

        metadata keys used by FileMemoryBackend:
            section (str): heading under which to write in project_summary.md
        """

    @abstractmethod
    async def get_summary(self) -> str:
        """Return the full project summary as a string (~2-5k tokens)."""

    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 5) -> str:
        """Return the most relevant passages for a query.

        FileMemoryBackend returns the full summary (no vector search).
        EverMemOSBackend will do semantic retrieval.
        """


class FileMemoryBackend(MemoryBackend):
    """Reads and writes project_summary.md inside a project directory.

    project_summary.md is a plain markdown file maintained by the Think agent
    after every major milestone. It is human-readable and git-trackable.
    """

    def __init__(self, project_dir: str | Path):
        self.summary_path = Path(project_dir) / "project_summary.md"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _read(self) -> str:
        if not self.summary_path.exists():
            return ""
        return self.summary_path.read_text(encoding="utf-8")

    def _write(self, text: str) -> None:
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path.write_text(text, encoding="utf-8")

    @staticmethod
    def _update_section(text: str, section: str, content: str) -> str:
        """Replace or append a markdown ## section."""
        heading = f"## {section}"
        pattern = rf"(^{re.escape(heading)}\n)(.*?)(?=^## |\Z)"
        replacement = f"{heading}\n{content.rstrip()}\n\n"
        if re.search(pattern, text, flags=re.MULTILINE | re.DOTALL):
            return re.sub(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
        # section not present — append
        return text.rstrip() + f"\n\n{heading}\n{content.rstrip()}\n"

    # ── MemoryBackend interface ───────────────────────────────────────────────

    async def store(self, content: str, metadata: dict) -> None:
        section = metadata.get("section", "Notes")
        updated = self._update_section(self._read(), section, content)
        self._write(updated)

    async def get_summary(self) -> str:
        return self._read()

    async def retrieve(self, query: str, top_k: int = 5) -> str:
        # No vector search — return full summary.
        # EverMemOSBackend will override this with semantic retrieval.
        return self._read()


def get_memory_backend(project_dir: str | Path) -> MemoryBackend:
    """Factory: returns the backend selected by config.MEMORY_BACKEND."""
    import config
    if config.MEMORY_BACKEND == "file":
        return FileMemoryBackend(project_dir)
    if config.MEMORY_BACKEND == "evermemos":
        from memory.evermemos import EverMemOSBackend  # deferred import
        return EverMemOSBackend(project_dir)
    raise ValueError(f"Unknown MEMORY_BACKEND: {config.MEMORY_BACKEND!r}")
