MODE: session_reflection

## Session conversation (last 20 turns):
{turns_text}

## Current project_memory.md:
{current_memory}

## Current global_memory.md:
{current_global}

Looking at this session holistically:
1. Were any reusable procedures discovered that would help in OTHER projects?
   If yes, return as GLOBAL_PROCEDURES: followed by the procedure description.
2. Did the user express preferences that apply across all projects?
   If yes, return as GLOBAL_PREFERENCES: followed by the preferences.
3. Any cross-project insights worth noting?
   If yes, return as GLOBAL_INSIGHTS: followed by the insight.

If nothing is worth promoting to global memory, return MODE: no_update.