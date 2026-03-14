"""Anthropic tool JSON defs for LASR rule optimization (wrapping v4cedars optimization/)."""

LASR_OPTIMIZE: dict = {
    "name": "lasr_optimize",
    "description": (
        "Run one generation of LASR (Logic-Aware Symbolic Regression) rule optimization. "
        "Mutates/crosses existing rules and returns the Pareto-front of improved candidates."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Pattern name to optimize rules for."},
            "seed_rule": {
                "type": "string",
                "description": "Starting rule expression. Uses the current best rule if omitted.",
            },
            "population_size": {
                "type": "integer",
                "description": "Number of candidate rules per generation. Defaults to 20.",
            },
            "n_generations": {
                "type": "integer",
                "description": "Number of LASR generations to run. Defaults to 5.",
            },
            "feature_subset": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Restrict search to these features. Uses all features if omitted.",
            },
        },
        "required": ["pattern"],
    },
}

LASR_MUTATE: dict = {
    "name": "lasr_mutate",
    "description": "Apply a single mutation to a rule and return the mutated rule string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rule": {"type": "string"},
            "mutation_type": {
                "type": "string",
                "enum": ["threshold_shift", "feature_swap", "operator_flip", "clause_add", "clause_drop"],
                "description": "Type of mutation to apply.",
            },
        },
        "required": ["rule"],
    },
}

LASR_CROSSOVER: dict = {
    "name": "lasr_crossover",
    "description": "Combine two rules via crossover and return the offspring rule string.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rule_a": {"type": "string"},
            "rule_b": {"type": "string"},
        },
        "required": ["rule_a", "rule_b"],
    },
}

COMPUTE_FITNESS: dict = {
    "name": "compute_fitness",
    "description": (
        "Compute the multi-objective fitness of a rule: "
        "returns {f1, precision, recall, complexity, fitness_score}."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rule": {"type": "string"},
            "pattern": {"type": "string"},
        },
        "required": ["rule", "pattern"],
    },
}

ALL_TOOLS = [LASR_OPTIMIZE, LASR_MUTATE, LASR_CROSSOVER, COMPUTE_FITNESS]
