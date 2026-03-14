"""Plot tool — interactive Plotly chart display.

Schema only — the executor lives in orchestrator/loop.py because it needs
the on_event callback to push the chart to the browser via WebSocket.
"""
from __future__ import annotations

# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "plot",
    "description": (
        "Generate an interactive Plotly chart and display it as a popup in the browser. "
        "Write Python code that builds a Plotly figure dict with 'data' and 'layout' keys "
        "and ends with `print(json.dumps(fig))`. "
        "Dark theme: paper_bgcolor='#0d1117', plot_bgcolor='#161b22', font color white. "
        "The chart appears immediately as an interactive popup with zoom, pan, and hover. "
        "Use this instead of matplotlib for ALL visualizations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "python_code": {
                "type": "string",
                "description": "Python code ending with `print(json.dumps(fig))` where fig is a Plotly figure dict.",
            },
            "title": {"type": "string", "description": "Title shown in the popup header."},
        },
        "required": ["python_code", "title"],
    },
}
