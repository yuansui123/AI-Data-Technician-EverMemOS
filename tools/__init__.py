"""Tool registry — all deterministic tools with their Anthropic schemas."""

from tools.bash import bash, SCHEMA as BASH_SCHEMA
from tools.vision import vision, SCHEMA as VISION_SCHEMA
from tools.read_file import read_file, SCHEMA as READ_FILE_SCHEMA
from tools.ask_user import ask_user, SCHEMA as ASK_USER_SCHEMA

# Tool lists for agents
EXPLORE_TOOLS = [BASH_SCHEMA, VISION_SCHEMA]
STATISTICS_TOOLS = [BASH_SCHEMA, VISION_SCHEMA]

__all__ = [
    "bash", "vision", "read_file", "ask_user",
    "BASH_SCHEMA", "VISION_SCHEMA", "READ_FILE_SCHEMA", "ASK_USER_SCHEMA",
    "EXPLORE_TOOLS", "STATISTICS_TOOLS",
]
