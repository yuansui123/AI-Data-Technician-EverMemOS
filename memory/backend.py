"""Memory abstraction layer.

Default: FileMemoryBackend — reads/writes project_memory.md.
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
            section (str): heading under which to write in project_memory.md
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
    """Reads and writes project_memory.md inside a project directory.

    project_memory.md is a plain markdown file maintained by the Think agent
    after every major milestone. It is human-readable and git-trackable.
    """

    def __init__(self, project_dir: str | Path):
        self.summary_path = Path(project_dir) / "project_memory.md"

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


class GlobalFileMemoryBackend(FileMemoryBackend):
    """File-based global memory at projects/_global/global_memory.md."""

    def __init__(self):
        import config
        global_dir = Path(config.PROJECTS_DIR) / "_global"
        global_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path = global_dir / "global_memory.md"


class HybridMemoryBackend(MemoryBackend):
    """Writes to both FileMemoryBackend and EverMemOSBackend simultaneously.

    Reads prefer EverMemOS (semantic search) with file as fallback.
    This ensures durability (git-trackable markdown) plus semantic search (EverMemOS).
    """

    def __init__(self, project_dir: str | Path) -> None:
        self.file_backend = FileMemoryBackend(project_dir)
        from memory.evermemos import EverMemOSBackend
        self.evermemos_backend = EverMemOSBackend(project_dir)

    async def store(self, content: str, metadata: dict) -> None:
        """Store to both backends. File write is synchronous and reliable;
        EverMemOS is best-effort (logs warning on failure)."""
        # Always write to file first (reliable, git-trackable)
        await self.file_backend.store(content, metadata)
        # Then write to EverMemOS (semantic search)
        try:
            await self.evermemos_backend.store(content, metadata)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Hybrid: EverMemOS store failed: %s", exc)

    async def get_summary(self) -> str:
        """Prefer EverMemOS summary (richer); fall back to file."""
        try:
            summary = await self.evermemos_backend.get_summary()
            if summary:
                return summary
        except Exception:
            pass
        return await self.file_backend.get_summary()

    async def retrieve(self, query: str, top_k: int = 5) -> str:
        """Use EverMemOS semantic search; fall back to file summary."""
        try:
            result = await self.evermemos_backend.retrieve(query, top_k=top_k)
            if result:
                return result
        except Exception:
            pass
        return await self.file_backend.retrieve(query, top_k=top_k)

    # ── Passthrough for extended EverMemOS methods ────────────────────────────

    async def retrieve_detailed(self, query: str, top_k: int = 8,
                                memory_types: list[str] | None = None) -> list[dict]:
        """Delegate to EverMemOS for detailed recall results."""
        try:
            return await self.evermemos_backend.retrieve_detailed(query, top_k=top_k, memory_types=memory_types)
        except Exception:
            return []

    async def store_chat_turn(self, role: str, content: str, sender_name: str = "") -> None:
        """Delegate chat turn logging to EverMemOS."""
        try:
            await self.evermemos_backend.store_chat_turn(role, content, sender_name)
        except Exception:
            pass

    async def search_profiles(self, user_id: str = "user", top_k: int = 5) -> str:
        """Delegate profile search to EverMemOS."""
        try:
            return await self.evermemos_backend.search_profiles(user_id, top_k)
        except Exception:
            return ""


class GlobalHybridMemoryBackend(HybridMemoryBackend):
    """Hybrid global memory — file + EverMemOS for cross-project scope."""

    def __init__(self) -> None:
        import config
        global_dir = Path(config.PROJECTS_DIR) / "_global"
        global_dir.mkdir(parents=True, exist_ok=True)
        self.file_backend = FileMemoryBackend.__new__(FileMemoryBackend)
        self.file_backend.summary_path = global_dir / "global_memory.md"
        from memory.evermemos import EverMemOSBackend
        self.evermemos_backend = EverMemOSBackend(global_dir)
        self.evermemos_backend.group_id = "adt_global"


def get_global_backend() -> MemoryBackend:
    """Factory for the global (cross-project) memory backend."""
    import config
    if config.MEMORY_BACKEND == "file":
        return GlobalFileMemoryBackend()
    if config.MEMORY_BACKEND == "hybrid":
        return GlobalHybridMemoryBackend()
    if config.MEMORY_BACKEND.startswith("evermemos"):
        from memory.evermemos import EverMemOSBackend
        backend = EverMemOSBackend(Path(config.PROJECTS_DIR) / "_global")
        backend.group_id = "adt_global"
        return backend
    raise ValueError(f"Unknown MEMORY_BACKEND: {config.MEMORY_BACKEND!r}")


def get_memory_backend(project_dir: str | Path) -> MemoryBackend:
    """Factory: returns the backend selected by config.MEMORY_BACKEND."""
    import config
    if config.MEMORY_BACKEND == "file":
        return FileMemoryBackend(project_dir)
    if config.MEMORY_BACKEND == "hybrid":
        return HybridMemoryBackend(project_dir)
    if config.MEMORY_BACKEND.startswith("evermemos"):
        from memory.evermemos import EverMemOSBackend  # deferred import
        return EverMemOSBackend(project_dir)
    raise ValueError(f"Unknown MEMORY_BACKEND: {config.MEMORY_BACKEND!r}")
