"""Anthropic tool JSON defs for feature computation (wrapping v4cedars features/ registry)."""

LIST_FEATURES: dict = {
    "name": "list_features",
    "description": (
        "List all registered feature functions available in the v4cedars feature registry. "
        "Returns feature names, descriptions, and required parameters."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter by category, e.g. 'spectral', 'temporal', 'entropy'.",
            }
        },
        "required": [],
    },
}

COMPUTE_FEATURE: dict = {
    "name": "compute_feature",
    "description": (
        "Compute a single feature for one signal and return the scalar value. "
        "Uses the v4cedars @feature registry."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "signal_id": {"type": "string"},
            "feature_name": {
                "type": "string",
                "description": "Registered feature function name, e.g. 'gamma_power'.",
            },
            "params": {
                "type": "object",
                "description": "Optional keyword arguments forwarded to the feature function.",
            },
        },
        "required": ["signal_id", "feature_name"],
    },
}

COMPUTE_FEATURE_MATRIX: dict = {
    "name": "compute_feature_matrix",
    "description": (
        "Compute a set of features across all labeled signals and save the result as "
        "projects/{Name}/cache/feature_matrix.parquet. Returns the path and shape."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of feature names to compute. Computes all registered features if omitted.",
            },
            "force_recompute": {
                "type": "boolean",
                "description": "Recompute even if cache exists. Defaults to false.",
            },
        },
        "required": [],
    },
}

LOAD_FEATURE_MATRIX: dict = {
    "name": "load_feature_matrix",
    "description": "Load the cached feature matrix from parquet. Returns column names and first 5 rows as JSON.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

ALL_TOOLS = [LIST_FEATURES, COMPUTE_FEATURE, COMPUTE_FEATURE_MATRIX, LOAD_FEATURE_MATRIX]
