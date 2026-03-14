"""
Mutation, crossover, and LLM prompt generation for rule evolution.

This module provides:
  - ``numeric_mutate``: fast, deterministic threshold perturbation
  - ``format_mutation_prompt``: LLM prompt for semantically guided mutation
  - ``format_crossover_prompt``: LLM prompt for rule crossover
  - ``format_concept_abstraction_prompt``: LLM prompt to extract concepts
  - ``format_concept_evolution_prompt``: LLM prompt to refine concept library
"""

import math
import random
import re
from typing import Dict, List, Optional

from tools.lasr.evaluation import evaluate_rule


# ---------------------------------------------------------------------------
# Numeric mutation (threshold perturbation)
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"(?<![a-zA-Z_])(-?\d+\.?\d*(?:[eE][+-]?\d+)?)")


def numeric_mutate(
    rule,
    exemplar_features: List[Dict[str, float]],
    exemplar_labels: List[bool],
    n_variants: int = 20,
    embedding_sims: Optional[List[float]] = None,
) -> list:
    """Generate rule variants by adjusting numeric thresholds +/-50 %.

    For every numeric literal in the rule string, generates *n_variants*
    random perturbations sampled uniformly in [0.5x, 1.5x] (or [-1.5|x|,
    -0.5|x|] for negative values, and small random values for zero).

    Each variant is evaluated and returned as a new Rule object with
    ``origin="numeric_mutate"``.

    Parameters
    ----------
    rule : Rule
        Source rule to mutate.
    exemplar_features : list of dict
        Feature dicts for evaluation.
    exemplar_labels : list of bool
        Ground-truth labels.
    n_variants : int
        Number of random perturbations to generate.
    embedding_sims : list of float or None
        Per-exemplar embedding similarity scores.

    Returns
    -------
    list of Rule objects (only those that parse and evaluate successfully).
    """
    # Late import to avoid circular dependency
    from tools.lasr.population import Rule, count_complexity

    rule_str = rule.rule if hasattr(rule, "rule") else str(rule)

    # Find all numeric literals and their positions
    matches = list(_NUMBER_RE.finditer(rule_str))
    if not matches:
        return []

    variants: List = []

    for _ in range(n_variants):
        new_rule = rule_str
        offset = 0  # track positional shift after replacements

        for m in matches:
            original = m.group(0)
            try:
                val = float(original)
            except ValueError:
                continue

            if abs(val) < 1e-12:
                # Zero: replace with a small random value
                perturbed = random.uniform(-0.1, 0.1)
            else:
                # Scale by random factor in [0.5, 1.5]
                factor = random.uniform(0.5, 1.5)
                perturbed = val * factor

            # Format to similar precision as original
            if "." in original or "e" in original.lower():
                replacement = f"{perturbed:.6g}"
            else:
                replacement = str(int(round(perturbed)))

            start = m.start() + offset
            end = m.end() + offset
            new_rule = new_rule[:start] + replacement + new_rule[end:]
            offset += len(replacement) - len(original)

        # De-duplicate: skip if identical to source
        if new_rule == rule_str:
            continue

        # Evaluate the variant
        try:
            metrics = evaluate_rule(
                new_rule, exemplar_features, exemplar_labels,
                embedding_sims=embedding_sims,
            )
        except Exception:
            continue

        new = Rule(
            rule=new_rule,
            fitness=metrics["fitness"],
            complexity=count_complexity(new_rule),
            generation=rule.generation + 1 if hasattr(rule, "generation") else 1,
            origin="numeric_mutate",
            true_positives=metrics["tp"],
            false_positives=metrics["fp"],
            true_negatives=metrics["tn"],
            false_negatives=metrics["fn"],
        )
        variants.append(new)

    return variants


# ---------------------------------------------------------------------------
# LLM prompt builders
# ---------------------------------------------------------------------------

def format_mutation_prompt(
    rule,
    feature_names: List[str],
    concept_library: List[str],
    misclassified_features: Optional[List[Dict[str, float]]] = None,
) -> str:
    """Generate a prompt for LLM-guided rule mutation.

    The prompt asks the LLM to propose improved variants of *rule* that
    fix misclassified exemplars while keeping the rule concise.

    Parameters
    ----------
    rule : Rule or str
        The current best rule.
    feature_names : list of str
        Available feature names the rule may reference.
    concept_library : list of str
        Named concepts (sub-expressions) the LLM may use.
    misclassified_features : list of dict or None
        Feature dicts for exemplars the current rule gets wrong.

    Returns
    -------
    str : the full prompt text.
    """
    rule_str = rule.rule if hasattr(rule, "rule") else str(rule)

    prompt_parts = [
        "You are an expert signal-classification rule optimizer.",
        "",
        "## Current Rule",
        f"```",
        f"{rule_str}",
        f"```",
    ]

    if hasattr(rule, "fitness"):
        prompt_parts.append(f"Fitness: {rule.fitness:.4f}")
    if hasattr(rule, "true_positives"):
        prompt_parts.append(
            f"TP={rule.true_positives}  FP={rule.false_positives}  "
            f"TN={rule.true_negatives}  FN={rule.false_negatives}"
        )

    prompt_parts += [
        "",
        "## Available Features",
        ", ".join(feature_names[:60]),  # Cap to avoid huge prompts
    ]

    if concept_library:
        prompt_parts += [
            "",
            "## Concept Library (reusable sub-expressions)",
        ]
        for concept in concept_library:
            prompt_parts.append(f"- {concept}")

    if misclassified_features:
        prompt_parts += [
            "",
            "## Misclassified Exemplars (feature snapshots)",
        ]
        for i, feat in enumerate(misclassified_features[:5]):
            # Show only most relevant features (top 8 by absolute value)
            sorted_feats = sorted(feat.items(), key=lambda kv: -abs(kv[1]))[:8]
            feat_str = ", ".join(f"{k}={v:.4g}" for k, v in sorted_feats)
            prompt_parts.append(f"  {i+1}. {feat_str}")

    prompt_parts += [
        "",
        "## Task",
        "Propose 3 to 5 improved rule variants. Each variant should:",
        "  1. Use only features from the Available Features list.",
        "  2. Fix as many misclassifications as possible.",
        "  3. Stay concise (prefer fewer AND/OR clauses).",
        "  4. Use Python boolean syntax (and, or, not, parentheses, comparisons).",
        "",
        "Return ONLY the rules, one per line, inside a ```rules code block.",
        "Example:",
        "```rules",
        "alpha_power_rel > 0.25 and spectral_slope < -1.2",
        "(theta_beta_ratio > 2.0 or alpha_power_rel > 0.3) and not line_noise_ratio > 5",
        "```",
    ]

    return "\n".join(prompt_parts)


def format_crossover_prompt(
    rule_a,
    rule_b,
    concept_library: List[str],
) -> str:
    """Generate a prompt for LLM-guided rule crossover.

    Asks the LLM to combine the best parts of two parent rules into
    offspring rules.

    Parameters
    ----------
    rule_a, rule_b : Rule or str
        Parent rules.
    concept_library : list of str
        Named concepts the LLM may incorporate.

    Returns
    -------
    str : the full prompt text.
    """
    rule_a_str = rule_a.rule if hasattr(rule_a, "rule") else str(rule_a)
    rule_b_str = rule_b.rule if hasattr(rule_b, "rule") else str(rule_b)

    fitness_a = f" (fitness={rule_a.fitness:.4f})" if hasattr(rule_a, "fitness") else ""
    fitness_b = f" (fitness={rule_b.fitness:.4f})" if hasattr(rule_b, "fitness") else ""

    prompt_parts = [
        "You are an expert signal-classification rule optimizer.",
        "",
        "## Parent Rule A" + fitness_a,
        "```",
        rule_a_str,
        "```",
        "",
        "## Parent Rule B" + fitness_b,
        "```",
        rule_b_str,
        "```",
    ]

    if concept_library:
        prompt_parts += [
            "",
            "## Concept Library (reusable sub-expressions)",
        ]
        for concept in concept_library:
            prompt_parts.append(f"- {concept}")

    prompt_parts += [
        "",
        "## Task",
        "Create 3 offspring rules by intelligently combining parts of both parents.",
        "Guidelines:",
        "  - Combine the strongest conditions from each parent.",
        "  - Try both AND-combination and OR-combination strategies.",
        "  - At least one offspring should be simpler than either parent.",
        "  - Use Python boolean syntax (and, or, not, parentheses, comparisons).",
        "",
        "Return ONLY the rules, one per line, inside a ```rules code block.",
    ]

    return "\n".join(prompt_parts)


def format_concept_abstraction_prompt(
    good_rules: List[str],
    bad_rules: List[str],
) -> str:
    """Generate a prompt to abstract concepts from high vs. low performing rules.

    The LLM is asked to identify recurring sub-expressions in good rules
    that distinguish them from bad rules, and name them as reusable
    concepts.

    Parameters
    ----------
    good_rules : list of str
        High-fitness rules.
    bad_rules : list of str
        Low-fitness rules.

    Returns
    -------
    str : the full prompt text.
    """
    prompt_parts = [
        "You are an expert at identifying patterns in signal-classification rules.",
        "",
        "## High-Performing Rules",
    ]
    for i, r in enumerate(good_rules[:10], 1):
        prompt_parts.append(f"  {i}. {r}")

    prompt_parts += ["", "## Low-Performing Rules"]
    for i, r in enumerate(bad_rules[:10], 1):
        prompt_parts.append(f"  {i}. {r}")

    prompt_parts += [
        "",
        "## Task",
        "Identify 3 to 5 reusable *concepts* -- named sub-expressions that appear",
        "frequently in the high-performing rules but NOT in the low-performing ones.",
        "",
        "For each concept, provide:",
        "  - A short name (snake_case, e.g. `high_alpha_state`)",
        "  - The boolean sub-expression it represents",
        "  - A one-sentence explanation of why it matters",
        "",
        "Format your answer as a numbered list:",
        "1. **concept_name**: `expression` -- explanation",
    ]

    return "\n".join(prompt_parts)


def format_concept_evolution_prompt(concept_library: List[str]) -> str:
    """Generate a prompt to evolve, refine, merge, or split concepts.

    Parameters
    ----------
    concept_library : list of str
        Current named concepts (format: ``"name: expression"``).

    Returns
    -------
    str : the full prompt text.
    """
    prompt_parts = [
        "You are an expert at refining signal-classification concept libraries.",
        "",
        "## Current Concept Library",
    ]
    for concept in concept_library:
        prompt_parts.append(f"  - {concept}")

    prompt_parts += [
        "",
        "## Task",
        "Evolve this concept library by doing any combination of:",
        "  1. **Refine** -- tighten or loosen thresholds in a concept.",
        "  2. **Merge** -- combine two related concepts into one more general concept.",
        "  3. **Split** -- break a broad concept into two more specific sub-concepts.",
        "  4. **Add** -- propose a new concept not yet in the library.",
        "  5. **Remove** -- drop a concept that is redundant or unhelpful.",
        "",
        "Return the updated concept library as a numbered list:",
        "1. **concept_name**: `expression` -- explanation",
        "",
        "Keep the library between 3 and 10 concepts.",
    ]

    return "\n".join(prompt_parts)
