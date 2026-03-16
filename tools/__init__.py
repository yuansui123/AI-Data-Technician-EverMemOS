"""Tool registry — all deterministic tools with their Anthropic schemas."""

from tools.bash import bash, SCHEMA as BASH_SCHEMA
from tools.vision import vision, SCHEMA as VISION_SCHEMA
from tools.read import read, SCHEMA as READ_SCHEMA
from tools.write import write, SCHEMA as WRITE_SCHEMA
from tools.ask import SCHEMA as ASK_SCHEMA
from tools.todo import SCHEMA as TODO_SCHEMA
from tools.plot import SCHEMA as PLOT_SCHEMA
from tools.recall import SCHEMA as RECALL_SCHEMA
from tools.remember import SCHEMA as REMEMBER_SCHEMA

# All tool schemas — single import for orchestrator
TOOL_SCHEMAS = [
    BASH_SCHEMA, READ_SCHEMA, WRITE_SCHEMA, VISION_SCHEMA,
    ASK_SCHEMA, TODO_SCHEMA, PLOT_SCHEMA, RECALL_SCHEMA, REMEMBER_SCHEMA,
]

# Tool list for task agent (bash + vision + read + write)
TASK_TOOLS = [BASH_SCHEMA, VISION_SCHEMA, READ_SCHEMA, WRITE_SCHEMA]

__all__ = [
    "bash", "vision", "read", "write",
    "BASH_SCHEMA", "VISION_SCHEMA", "READ_SCHEMA", "WRITE_SCHEMA", "ASK_SCHEMA",
    "TODO_SCHEMA", "PLOT_SCHEMA", "RECALL_SCHEMA", "REMEMBER_SCHEMA",
    "TOOL_SCHEMAS", "TASK_TOOLS",
]
