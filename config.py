"""Single source of truth for model IDs, token budgets, paths, and backend config."""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Root of this repo — absolute regardless of where the server is launched from.
_HERE = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def validate_sandbox_backend(name: str) -> str:
    backend = (name or "local").strip().lower()
    if backend not in {"local", "docker"}:
        raise ValueError("SANDBOX_BACKEND must be 'local' or 'docker'")
    return backend


# ── Model IDs ──────────────────────────────────────────────────────────────────
ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
THINK_MODEL        = "claude-sonnet-4-6"
TASK_MODEL         = "claude-sonnet-4-6"
VISION_MODEL       = "gemini-2.5-flash"

# ── Token budgets (extended thinking) ─────────────────────────────────────────
ORCHESTRATOR_THINKING_BUDGET = 4000    # reason before choosing tools/agents
THINK_THINKING_BUDGET        = 3000    # deep reasoning for summaries, compaction, LASR

# ── Iteration / tool-use limits ───────────────────────────────────────────────
ORCHESTRATOR_LIMITS = {"simple": 5, "moderate": 10, "complex": 25}
TASK_MAX_ITER       = 15

# ── Context management ────────────────────────────────────────────────────────
AUTO_COMPACT_THRESHOLD = 40_000   # tokens; triggers Think-based compaction
MEMORY_UPDATE_INTERVAL = 5        # user messages between periodic Think memory updates

# ── Memory backend ────────────────────────────────────────────────────────────
# Options: "file" | "evermemos_local" | "evermemos_cloud" | "hybrid"
# "hybrid" writes to both file (git-trackable markdown) AND EverMemOS (semantic search)
MEMORY_BACKEND = "hybrid"

# ── Sandbox backend ───────────────────────────────────────────────────────────
# Isolation is per user turn (orchestrator) and per task invocation.
# V1 network is always disabled and cannot be overridden by model/user input.
SANDBOX_BACKEND = validate_sandbox_backend(os.getenv("SANDBOX_BACKEND", "local"))
SANDBOX_DOCKER_IMAGE = os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.11-slim")
SANDBOX_COMMAND_TIMEOUT_SECONDS = _env_int("SANDBOX_COMMAND_TIMEOUT_SECONDS", 120)
SANDBOX_NETWORK_ENABLED = False
SANDBOX_CPUS = os.getenv("SANDBOX_CPUS", "1")
SANDBOX_MEMORY = os.getenv("SANDBOX_MEMORY", "2g")
SANDBOX_PIDS_LIMIT = _env_int("SANDBOX_PIDS_LIMIT", 256)

# EverMemOS endpoints — resolved automatically from MEMORY_BACKEND
_EVERMEMOS_URLS = {
    "evermemos_local": "http://localhost:1995/api/v1",
    "evermemos_cloud": "https://api.evermind.ai/api/v0",
}
EVERMEMOS_BASE_URL = _EVERMEMOS_URLS.get(MEMORY_BACKEND, _EVERMEMOS_URLS["evermemos_cloud"])
EVERMEMOS_API_KEY  = os.getenv("EVERMEMOS_API_KEY", "")  # only needed for cloud

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECTS_DIR = str(_HERE / "projects")

# ── API keys (from environment) ───────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")   # Gemini / Vision
