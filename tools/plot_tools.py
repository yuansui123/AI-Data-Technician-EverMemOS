"""Anthropic tool JSON defs for plotting (wrapping v4cedars plot/ registry)."""

PLOT_SIGNAL: dict = {
    "name": "plot_signal",
    "description": (
        "Plot a raw time-series signal (or a window of it) and save as PNG to "
        "projects/{Name}/tmp/plots/. Returns the saved file path."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "signal_id": {"type": "string"},
            "channel": {"type": "integer", "description": "Channel index. Defaults to 0."},
            "t_start": {"type": "number", "description": "Start time in seconds."},
            "t_end": {"type": "number", "description": "End time in seconds."},
            "title": {"type": "string"},
        },
        "required": ["signal_id"],
    },
}

PLOT_POWER_SPECTRUM: dict = {
    "name": "plot_power_spectrum",
    "description": (
        "Plot the power spectral density of a signal (Welch method) and save as PNG. "
        "Returns the saved file path."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "signal_id": {"type": "string"},
            "channel": {"type": "integer"},
            "freq_max": {
                "type": "number",
                "description": "Upper frequency limit in Hz. Defaults to fs/2.",
            },
        },
        "required": ["signal_id"],
    },
}

PLOT_FEATURE_DISTRIBUTIONS: dict = {
    "name": "plot_feature_distributions",
    "description": (
        "Plot per-class feature distributions (violin + strip plot) for selected features "
        "using the cached feature matrix. Returns the saved PNG path."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Feature names to plot. Plots all if omitted.",
            },
            "pattern": {"type": "string", "description": "Pattern name for class labels."},
        },
        "required": ["pattern"],
    },
}

PLOT_RULE_DECISION_BOUNDARY: dict = {
    "name": "plot_rule_decision_boundary",
    "description": (
        "Scatter-plot two features coloured by rule prediction vs ground truth label. "
        "Returns the saved PNG path."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rule": {"type": "string"},
            "pattern": {"type": "string"},
            "x_feature": {"type": "string"},
            "y_feature": {"type": "string"},
        },
        "required": ["rule", "pattern", "x_feature", "y_feature"],
    },
}

ALL_TOOLS = [PLOT_SIGNAL, PLOT_POWER_SPECTRUM, PLOT_FEATURE_DISTRIBUTIONS, PLOT_RULE_DECISION_BOUNDARY]
