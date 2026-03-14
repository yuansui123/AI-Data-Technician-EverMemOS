"""Read file tool — deterministic file reader, no LLM.

Reads any text file and returns its contents, with optional offset/limit for paging.
"""
from __future__ import annotations

from pathlib import Path


def read(
    path: str | Path,
    max_chars: int = 8000,
    offset_chars: int = 0,
) -> dict:
    """Read a file and return its content with paging metadata."""
    path = Path(path)
    if not path.exists():
        return {"response": f"File not found: {path}"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"response": f"Could not read {path.name}: {e}"}

    chunk = text[offset_chars: offset_chars + max_chars]
    remaining = max(0, len(text) - offset_chars - max_chars)
    footer = (
        f"\n\n[{remaining} more characters -- call read with offset_chars={offset_chars + max_chars}]"
        if remaining else ""
    )
    return {"response": f"```{path.suffix.lstrip('.')}\n{chunk}\n```{footer}"}


# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "read",
    "description": (
        "Read any file and return its raw content -- deterministic, no LLM. "
        "Use this to inspect scripts (.py, .m), config files, CSVs, text files, or any file "
        "whose content you need to see. Returns up to max_chars characters (default 8000). "
        "For .mat binary data files use explore_dataset instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (default 8000)",
            },
            "offset_chars": {
                "type": "integer",
                "description": "Skip first N characters (for paging through large files)",
            },
        },
        "required": ["path"],
    },
}
