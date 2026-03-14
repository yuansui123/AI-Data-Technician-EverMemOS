"""Workflow: ingest_documents

Sequence:
  1. Bash: extract text from each document (PDF → pdftotext / PyMuPDF, etc.)
  2. Think: synthesise key metadata → project_summary.md §Dataset Context
  3. Optionally trigger explore_dataset if a data_dir is also provided
"""
from __future__ import annotations

from pathlib import Path


async def ingest_documents(
    file_paths: list[str | Path],
    project_dir: str | Path,
    memory_backend=None,
    data_dir: str | Path | None = None,
    context_carry: dict | None = None,
) -> dict:
    """Extract and store knowledge from documents (PDFs, READMEs, protocol files).

    Returns {extracted_texts, summary_stored, explore_report (if data_dir given)}.
    """
    from tools.bash import bash
    from agents.think import think

    extracted: dict[str, str] = {}

    for fp in file_paths:
        fp = Path(fp)
        text = await _extract_text(fp, project_dir)
        extracted[fp.name] = text

    # Step 2 — Think: synthesise
    combined = "\n\n".join(
        f"### {name}\n{text[:4000]}" for name, text in extracted.items()
    )
    think_input = (
        "Extract key metadata from these documents for a neural signal analysis project. "
        "Include: dataset description, recording protocol, sampling rate, channel count, "
        "artifact types mentioned, signal patterns of interest, labeling conventions.\n\n"
        + combined
    )

    if memory_backend:
        await think(
            content=think_input,
            section="Dataset Context",
            memory_backend=memory_backend,
        )

    result: dict = {"extracted_texts": extracted, "summary_stored": memory_backend is not None}

    # Step 3 — optionally explore
    if data_dir:
        from workflows.explore_dataset import explore_dataset
        report = await explore_dataset(
            data_dir=data_dir,
            project_dir=project_dir,
            memory_backend=memory_backend,
            context_carry=context_carry,
        )
        result["explore_report"] = report

    return result


async def _extract_text(fp: Path, project_dir: str | Path) -> str:
    from tools.bash import bash

    if fp.suffix.lower() == ".pdf":
        # Use temp-file pattern to avoid shell-quoting issues with Windows paths.
        # sort=True reconstructs reading order, which fixes word-split artifacts
        # in academic papers that have line numbers or multi-column layouts.
        py = (
            f"import fitz\n"
            f"doc = fitz.open(r'{fp}')\n"
            f"pages = [p.get_text(sort=True) for p in doc]\n"
            f"print('\\n\\n'.join(pages))\n"
        )
        cmd = (
            f"$code = @'\n{py}\n'@\n"
            f"$code | Out-File -Encoding utf8 C:\\Windows\\Temp\\ingest_pdf.py\n"
            f"python C:\\Windows\\Temp\\ingest_pdf.py"
        )
        result = await bash(cmd, cwd=str(project_dir))
        if result.ok and result.stdout:
            return result.stdout
        # fallback
        result2 = await bash(f'pdftotext "{fp}" -', cwd=str(project_dir))
        return result2.stdout or f"[could not extract {fp.name}]"

    if fp.suffix.lower() in {".txt", ".md", ".rst"}:
        return fp.read_text(encoding="utf-8", errors="replace")[:8000]

    return f"[unsupported format: {fp.suffix}]"
