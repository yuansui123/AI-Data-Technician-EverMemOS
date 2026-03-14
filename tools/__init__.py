"""Tool registry — collect all Anthropic-format tool JSON defs."""
from tools.signal_tools import ALL_TOOLS as SIGNAL_TOOLS
from tools.feature_tools import ALL_TOOLS as FEATURE_TOOLS
from tools.rule_tools import ALL_TOOLS as RULE_TOOLS
from tools.plot_tools import ALL_TOOLS as PLOT_TOOLS
from tools.optimization_tools import ALL_TOOLS as OPTIMIZATION_TOOLS

# Primitive tools always available to Explore / Statistics
BASH_TOOL: dict = {
    "name": "bash_execute",
    "description": (
        "Execute a shell command via Windows PowerShell. "
        "Use this to run Python scripts, list files, compute statistics, extract PDF text. "
        "Multi-line python -c is supported. Use single quotes inside python -c strings: "
        "python -c \"import sys; print('ok')\". "
        "Use Get-ChildItem or dir for listing. Select-Object -First N replaces head."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "cwd": {"type": "string", "description": "Working directory. Defaults to project root."},
            "timeout": {"type": "integer", "description": "Timeout in seconds. Defaults to 60."},
        },
        "required": ["command"],
    },
}

VISION_TOOL: dict = {
    "name": "vision_analyze",
    "description": (
        "Send an image to Gemini 2.0 Flash for analysis. "
        "Returns description, likely_pattern, rule_assessment, suggested_feature_gap."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Absolute path to the PNG/JPG."},
            "context": {
                "type": "object",
                "description": (
                    "Optional context dict: signal_id, known_patterns, current_rule, "
                    "TP, FP, FN, TN counts."
                ),
            },
        },
        "required": ["image_path"],
    },
}

# Convenient pre-built tool lists
EXPLORE_TOOLS = [BASH_TOOL, VISION_TOOL]
STATISTICS_TOOLS = [BASH_TOOL, VISION_TOOL] + FEATURE_TOOLS + RULE_TOOLS + OPTIMIZATION_TOOLS

ALL_DOMAIN_TOOLS = SIGNAL_TOOLS + FEATURE_TOOLS + RULE_TOOLS + PLOT_TOOLS + OPTIMIZATION_TOOLS

__all__ = [
    "BASH_TOOL", "VISION_TOOL",
    "EXPLORE_TOOLS", "STATISTICS_TOOLS", "ALL_DOMAIN_TOOLS",
    "SIGNAL_TOOLS", "FEATURE_TOOLS", "RULE_TOOLS", "PLOT_TOOLS", "OPTIMIZATION_TOOLS",
]
