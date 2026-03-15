MODE: memory_update

## Current project_memory.md
{current_memory}

## Recent conversation
{turns_text}

Update project_memory.md with any new information from the conversation.
- Return ONLY the ## sections that need changes (with full updated content for each).
- Prune stale/superseded facts. Keep only current truth.
- Each section ≤ 300 words. Total memory ≤ 3k tokens. Consolidate if growing too long.
- If nothing needs updating, return MODE: no_update.