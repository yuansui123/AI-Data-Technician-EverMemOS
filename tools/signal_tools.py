"""Anthropic tool JSON defs for signal I/O (wrapping v4cedars feature_store / label_store)."""

LIST_SIGNALS: dict = {
    "name": "list_signals",
    "description": (
        "List available signal IDs in the project's feature store. "
        "Returns a JSON array of signal IDs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter IDs, e.g. 't002_*'.",
            }
        },
        "required": [],
    },
}

LOAD_SIGNAL: dict = {
    "name": "load_signal",
    "description": (
        "Load a raw time-series signal from the feature store and return basic metadata "
        "(n_samples, fs, duration_s, channel_count) plus a preview (first 200 samples as JSON)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "signal_id": {"type": "string", "description": "The signal ID to load."},
            "channel": {
                "type": "integer",
                "description": "Zero-based channel index. Defaults to 0.",
            },
        },
        "required": ["signal_id"],
    },
}

GET_LABELS: dict = {
    "name": "get_labels",
    "description": "Return the label dict for one or all signals from the label store.",
    "input_schema": {
        "type": "object",
        "properties": {
            "signal_id": {
                "type": "string",
                "description": "Signal ID. If omitted, returns all labels.",
            }
        },
        "required": [],
    },
}

SET_LABEL: dict = {
    "name": "set_label",
    "description": "Write a label for a signal into the label store.",
    "input_schema": {
        "type": "object",
        "properties": {
            "signal_id": {"type": "string"},
            "label": {
                "type": "string",
                "description": "Label value, e.g. 'muscle_artifact', 'clean', 'spike'.",
            },
            "confidence": {
                "type": "number",
                "description": "0.0–1.0 confidence score. Defaults to 1.0.",
            },
        },
        "required": ["signal_id", "label"],
    },
}

ALL_TOOLS = [LIST_SIGNALS, LOAD_SIGNAL, GET_LABELS, SET_LABEL]
