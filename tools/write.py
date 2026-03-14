"""Write file tool — deterministic file writer, no LLM.

Writes UTF-8 text to a file with project directory safety guard.
Creates parent directories if needed.
"""
from __future__ import annotations

from pathlib import Path


def write(
    path: str | Path,
    content: str,
    project_dir: str | Path | None = None,
) -> dict:
    """Write *content* to *path*. Returns confirmation with byte count."""
    path = Path(path).resolve()

    # Safety: if project_dir given, refuse writes outside it
    if project_dir is not None:
        project_dir = Path(project_dir).resolve()
        if not str(path).startswith(str(project_dir)):
            return {"response": f"Refused: path {path} is outside project directory {project_dir}"}

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"response": f"Wrote {len(content.encode('utf-8'))} bytes to {path}"}
    except Exception as e:
        return {"response": f"Could not write {path}: {e}"}


# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "write",
    "description": (
        "Write text content to a file -- deterministic, no LLM. "
        "Creates parent directories if needed. Use for saving scripts, configs, "
        "CSVs, or any text output. Path must be inside the project directory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to write to"},
            "content": {"type": "string", "description": "Text content to write"},
        },
        "required": ["path", "content"],
    },
}
