MODE: memory_update

## Current project_memory.md
{current_memory}

## Recent conversation
{turns_text}

Update project_memory.md with any new information from the conversation.
- Return ONLY the ## sections that need changes (with full updated content for each).
- Prune stale/superseded facts. Keep only current truth.
- Each section ≤ 500 words. Total memory ≤ 5k tokens. Consolidate if growing too long.
- The ## Dataset section is critical — it must include: file paths, file format and how to load them, column names/keys, sampling rate, number of samples, data shape, and any other details an agent would need to work with the data WITHOUT re-exploring. Think of it as a cheat sheet.
- If nothing needs updating, return MODE: no_update.