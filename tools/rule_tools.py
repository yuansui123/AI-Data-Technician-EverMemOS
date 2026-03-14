"""Anthropic tool JSON defs for rule evaluation (wrapping v4cedars rules.py)."""

APPLY_RULE: dict = {
    "name": "apply_rule",
    "description": (
        "Evaluate a boolean rule string against the feature matrix and return "
        "TP, FP, FN, TN counts plus the list of FP and FN signal IDs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rule": {
                "type": "string",
                "description": (
                    "Boolean expression using feature names and thresholds, "
                    "e.g. 'gamma_power > 0.4 AND burst_rate < 0.2'."
                ),
            },
            "pattern": {
                "type": "string",
                "description": "Pattern name this rule targets, e.g. 'muscle_artifact'.",
            },
        },
        "required": ["rule", "pattern"],
    },
}

LIST_RULES: dict = {
    "name": "list_rules",
    "description": "Return all saved rules from projects/{Name}/rules/classification.json.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Filter by pattern name. Returns all rules if omitted.",
            }
        },
        "required": [],
    },
}

SAVE_RULE: dict = {
    "name": "save_rule",
    "description": "Save a validated rule to projects/{Name}/rules/classification.json.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rule": {"type": "string"},
            "pattern": {"type": "string"},
            "fitness": {
                "type": "number",
                "description": "Rule fitness score (higher is better).",
            },
            "metrics": {
                "type": "object",
                "description": "Dict with TP, FP, FN, TN, precision, recall, f1.",
            },
        },
        "required": ["rule", "pattern"],
    },
}

ALL_TOOLS = [APPLY_RULE, LIST_RULES, SAVE_RULE]
