"""Read file tool — deterministic file reader, no LLM.

Reads text files, PDFs (.pdf), and MATLAB data files (.mat).
Supports optional offset/limit for paging through large content.
"""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Format-specific readers
# ---------------------------------------------------------------------------

def _read_pdf(path: Path, max_chars: int, offset_chars: int) -> dict:
    """Extract text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"response": "PyMuPDF (fitz) is not installed — cannot read PDF files."}

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        return {"response": f"Could not open PDF {path.name}: {e}"}

    pages: list[str] = []
    for i, page in enumerate(doc):
        pages.append(f"--- PAGE {i + 1} ---\n{page.get_text()}")
    doc.close()

    text = "\n".join(pages)
    chunk = text[offset_chars: offset_chars + max_chars]
    remaining = max(0, len(text) - offset_chars - max_chars)
    footer = (
        f"\n\n[{remaining} more characters -- call read with offset_chars={offset_chars + max_chars}]"
        if remaining else ""
    )
    return {"response": f"```\n{chunk}\n```{footer}"}


def _read_mat(path: Path) -> dict:
    """Inspect a .mat file and return a structure summary (keys, shapes, dtypes)."""
    # Try scipy.io first (MATLAB v4/v5/v6), fall back to h5py (v7.3 / HDF5).
    try:
        import scipy.io as sio
        mat = sio.loadmat(str(path), simplify_cells=True)
        entries: list[str] = []
        for k, v in sorted(mat.items()):
            if k.startswith("_"):
                continue
            import numpy as np
            if isinstance(v, np.ndarray):
                entries.append(f"  {k}: ndarray shape={v.shape} dtype={v.dtype}")
            elif isinstance(v, dict):
                entries.append(f"  {k}: dict keys={list(v.keys())}")
            elif isinstance(v, list):
                entries.append(f"  {k}: list len={len(v)}")
            else:
                entries.append(f"  {k}: {type(v).__name__} = {v}")
        header = f"MAT file (scipy): {path.name}\n"
        return {"response": header + "\n".join(entries)}
    except NotImplementedError:
        pass  # v7.3 — fall through to h5py
    except Exception as e:
        # Unexpected error with scipy — still try h5py
        pass

    try:
        import h5py
        import numpy as np
    except ImportError:
        return {"response": "Neither scipy.io nor h5py could read this .mat file."}

    try:
        entries = []
        with h5py.File(str(path), "r") as f:
            def _visit(name: str, obj: object) -> None:
                if isinstance(obj, h5py.Dataset):
                    ds = obj
                    info = f"  {name}: shape={ds.shape} dtype={ds.dtype}"
                    # Show scalar or small values inline
                    if ds.size == 1:
                        info += f" value={ds[()].flat[0]}"
                    elif ds.size <= 10:
                        info += f" values={np.array(ds).flatten().tolist()}"
                    entries.append(info)
                elif isinstance(obj, h5py.Group):
                    entries.append(f"  {name}/ (group, {len(obj)} items)")
            f.visititems(_visit)
        header = f"MAT file (HDF5/v7.3): {path.name}\n"
        return {"response": header + "\n".join(entries)}
    except Exception as e:
        return {"response": f"Could not read {path.name}: {e}"}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def read(
    path: str | Path,
    max_chars: int = 8000,
    offset_chars: int = 0,
) -> dict:
    """Read a file and return its content with paging metadata."""
    path = Path(path)
    if not path.exists():
        return {"response": f"File not found: {path}"}

    suffix = path.suffix.lower()

    # PDF files
    if suffix == ".pdf":
        return _read_pdf(path, max_chars, offset_chars)

    # MATLAB data files
    if suffix == ".mat":
        return _read_mat(path)

    # Default: text file
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
        "Read any file and return its content -- deterministic, no LLM. "
        "Handles text files (.py, .m, .csv, etc.), PDFs (.pdf, extracts text), "
        "and MATLAB data files (.mat, returns structure summary with keys/shapes/dtypes). "
        "Returns up to max_chars characters (default 8000); use offset_chars to page."
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
