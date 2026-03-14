"""Single source of truth for model IDs, token budgets, paths, and backend config."""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Root of this repo — absolute regardless of where the server is launched from.
_HERE = Path(__file__).resolve().parent

# ── Model IDs ──────────────────────────────────────────────────────────────────
ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
THINK_MODEL        = "claude-sonnet-4-6"
EXPLORE_MODEL      = "claude-sonnet-4-6"
STATISTICS_MODEL   = "claude-sonnet-4-6"
CODE_MODEL         = "claude-sonnet-4-6"
VISION_MODEL       = "gemini-2.5-flash"

# ── Token budgets (extended thinking) ─────────────────────────────────────────
ORCHESTRATOR_THINKING_BUDGET =  0      # disabled for now
THINK_THINKING_BUDGET        =  0      # disabled for now
EXPLORE_THINKING_BUDGET      =  0      # disabled for now
STATISTICS_THINKING_BUDGET   =  0      # disabled for now

# ── Iteration / tool-use limits ───────────────────────────────────────────────
ORCHESTRATOR_LIMITS = {"simple": 5, "moderate": 10, "complex": 25}
EXPLORE_MAX_ITER    = 10
STATISTICS_MAX_ITER = 7
CODE_MAX_TOOL_USES  = 3
CODEGEN_MAX_ITER    = 8   # bash/read exploration + generate → run → fix loop
CODEGEN_THINKING_BUDGET = 2000  # per-iteration thinking for planning before tool calls

# ── Context management ────────────────────────────────────────────────────────
AUTO_COMPACT_THRESHOLD = 40_000   # tokens; triggers Think-based compaction

# ── Memory backend ────────────────────────────────────────────────────────────
MEMORY_BACKEND = "file"           # "file" | "evermemos_local" | "evermemos_cloud"

# EverMemOS endpoints — resolved automatically from MEMORY_BACKEND
_EVERMEMOS_URLS = {
    "evermemos_local": "http://localhost:1995/api/v1",
    "evermemos_cloud": "https://api.evermind.ai/api/v0",
}
EVERMEMOS_BASE_URL = _EVERMEMOS_URLS.get(MEMORY_BACKEND, _EVERMEMOS_URLS["evermemos_local"])
EVERMEMOS_API_KEY  = os.getenv("EVERMEM_API_KEY", "")  # only needed for cloud

# ── Paths ─────────────────────────────────────────────────────────────────────
V4CEDARS_LIB = r"C:\Users\yuans\Desktop\ClaudeCode\v4cedars\lib"
PROJECTS_DIR = str(_HERE / "projects")

# ── API keys (from environment) ───────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")   # Gemini / Vision
