"""Plot tool — Plotly (interactive) and matplotlib (static PNG) chart display.

Schema only — the executor lives in orchestrator/loop.py because it needs
the on_event callback to push the chart to the browser via WebSocket.
"""
from __future__ import annotations

# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "plot",
    "description": (
        "Generate a chart and display it in the browser. Supports two modes:\n"
        "• **Plotly (interactive):** Write Python code that builds a Plotly figure dict "
        "and ends with `print(json.dumps(fig))`. Opens as an interactive popup with zoom/pan/hover. "
        "Dark theme: paper_bgcolor='#0d1117', plot_bgcolor='#161b22', font color white.\n"
        "• **matplotlib (static):** Write Python code using matplotlib/MNE/scipy. "
        "Just create figures normally — they are auto-captured as PNG and displayed inline. "
        "Dark theme is applied automatically.\n"
        "Use Plotly for interactive exploration; matplotlib for scientific plots "
        "(spectrograms, topomaps, PSD, complex multi-panel figures)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "python_code": {
                "type": "string",
                "description": (
                    "Python code that produces a visualization. "
                    "For Plotly: end with `print(json.dumps(fig))`. "
                    "For matplotlib: just create figures (plt.plot, plt.imshow, etc.) — auto-captured."
                ),
            },
            "title": {"type": "string", "description": "Title shown in the popup header."},
        },
        "required": ["python_code", "title"],
    },
}
