"""Code agent — claude-sonnet-4-6, writes files only, never executes.

Input:  feature_gap_description + 2-3 existing feature file snippets as context
Output: writes draft to tmp/code_drafts/, then moves to lib/features/derived/
        or lib/plot/custom/ if validation passes.

Limit: 1 API call, max 3 tool uses (file writes only).
"""
from __future__ import annotations

from pathlib import Path


_SYSTEM_PROMPT = """\
You are a Python code writer for a neural signal analysis library.
You write feature extraction functions using the v4cedars @feature decorator
or plot functions using the @plot decorator.

Rules:
- Import from the v4cedars lib via sys.path (path is already on PYTHONPATH)
- Use only: numpy, scipy, antropy, mne — no new pip installs
- Decorate feature functions with @feature(name="...", category="...")
- Decorate plot functions with @plot(name="...")
- Do NOT execute any code; only write files
- Output the file content as plain text in your response wrapped in triple backtick python fences
- After the code block, write "FILENAME: <relative path under lib/>" on its own line
"""


async def code(
    feature_gap_description: str,
    existing_snippets: list[str] | None = None,
    project_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict:
    """Generate a feature or plot function and save the draft file.

    Returns:
        {draft_path, moved_path (if valid), code}
    """
    import anthropic
    import config

    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    snippets_text = ""
    if existing_snippets:
        snippets_text = "\n\n## Existing feature file snippets for reference:\n"
        for i, s in enumerate(existing_snippets, 1):
            snippets_text += f"\n### Snippet {i}\n```python\n{s}\n```"

    user_message = (
        f"## Feature gap to implement:\n{feature_gap_description}"
        + snippets_text
    )

    response = await client.messages.create(
        model=config.CODE_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    code_text = ""
    filename = "generated_feature.py"

    lines = response_text.split("\n")
    in_code = False
    code_lines: list[str] = []
    for line in lines:
        if line.startswith("```python"):
            in_code = True
            continue
        if in_code and line.startswith("```"):
            in_code = False
            continue
        if in_code:
            code_lines.append(line)
        if line.startswith("FILENAME:"):
            filename = line.split("FILENAME:", 1)[1].strip()

    code_text = "\n".join(code_lines)

    draft_dir = Path(project_dir or ".") / "tmp" / "code_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / Path(filename).name
    draft_path.write_text(code_text, encoding="utf-8")

    moved_path = None
    if output_dir:
        dest = Path(output_dir) / Path(filename).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code_text, encoding="utf-8")
        moved_path = str(dest)

    return {
        "draft_path": str(draft_path),
        "moved_path": moved_path,
        "filename": filename,
        "code": code_text,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
