"""
Pareto frontier extraction for multi-objective rule optimization.

Objectives:
  - Maximize fitness/accuracy (index 0)
  - Minimize complexity (index 1)

This module provides functions to identify non-dominated (Pareto-optimal)
rules and select the simplest rule that meets an accuracy threshold.
"""

from typing import List, Optional


def is_dominated(point: tuple, other: tuple) -> bool:
    """Check if *point* is dominated by *other*.

    A point is dominated when the other point is at least as good on every
    objective AND strictly better on at least one.

    Objectives:
      - Index 0: fitness/accuracy  (higher is better)
      - Index 1: complexity        (lower is better)

    Parameters
    ----------
    point : (fitness, complexity)
    other : (fitness, complexity)

    Returns
    -------
    True if *other* dominates *point*.
    """
    fitness_p, complexity_p = point
    fitness_o, complexity_o = other

    # other is at least as good on both objectives
    at_least_as_good = (fitness_o >= fitness_p) and (complexity_o <= complexity_p)
    # other is strictly better on at least one objective
    strictly_better = (fitness_o > fitness_p) or (complexity_o < complexity_p)

    return at_least_as_good and strictly_better


def extract_pareto_front(rules: list) -> List[int]:
    """Extract indices of Pareto-optimal rules.

    Each element in *rules* must be a dict (or dict-like) with at least
    ``'fitness'`` and ``'complexity'`` keys.

    Parameters
    ----------
    rules : list of dict
        Each dict must contain 'fitness' (float, higher=better) and
        'complexity' (int, lower=better).

    Returns
    -------
    List of indices into *rules* that are non-dominated, sorted by
    ascending complexity then descending fitness.
    """
    if not rules:
        return []

    n = len(rules)
    dominated = [False] * n

    for i in range(n):
        if dominated[i]:
            continue
        pi = (rules[i]["fitness"], rules[i]["complexity"])
        for j in range(n):
            if i == j or dominated[j]:
                continue
            pj = (rules[j]["fitness"], rules[j]["complexity"])
            if is_dominated(pi, pj):
                dominated[i] = True
                break

    pareto_indices = [i for i in range(n) if not dominated[i]]

    # Sort by ascending complexity, then descending fitness for ties
    pareto_indices.sort(key=lambda i: (rules[i]["complexity"], -rules[i]["fitness"]))
    return pareto_indices


def select_by_threshold(
    rules: list,
    pareto_indices: List[int],
    min_accuracy: float = 0.8,
) -> Optional[int]:
    """Select the simplest Pareto-optimal rule that meets *min_accuracy*.

    From the Pareto front (already sorted by ascending complexity), return
    the index of the first rule whose fitness >= *min_accuracy*.  If no
    rule meets the threshold, return the index of the highest-fitness rule
    on the Pareto front.

    Parameters
    ----------
    rules : list of dict
        Same format as :func:`extract_pareto_front`.
    pareto_indices : list of int
        Output of :func:`extract_pareto_front`.
    min_accuracy : float
        Minimum fitness threshold (default 0.8).

    Returns
    -------
    int or None
        Index into *rules*, or None if *pareto_indices* is empty.
    """
    if not pareto_indices:
        return None

    # Pareto indices are sorted by ascending complexity already
    for idx in pareto_indices:
        if rules[idx]["fitness"] >= min_accuracy:
            return idx

    # Fallback: return the rule with the highest fitness on the front
    best_idx = max(pareto_indices, key=lambda i: rules[i]["fitness"])
    return best_idx


def pareto_summary(rules: list, pareto_indices: List[int]) -> str:
    """Build a human-readable Pareto front summary table.

    Parameters
    ----------
    rules : list of dict
        Each dict should have at least 'fitness', 'complexity', and 'rule'.
    pareto_indices : list of int
        Output of :func:`extract_pareto_front`.

    Returns
    -------
    Formatted multi-line string.
    """
    if not pareto_indices:
        return "Pareto front is empty."

    lines = []
    lines.append("=" * 80)
    lines.append("PARETO FRONT SUMMARY")
    lines.append("=" * 80)
    lines.append(
        f"{'Rank':<6}{'Fitness':>10}{'Complexity':>12}  {'Rule'}"
    )
    lines.append("-" * 80)

    for rank, idx in enumerate(pareto_indices, start=1):
        r = rules[idx]
        fitness = r.get("fitness", 0.0)
        complexity = r.get("complexity", 0)
        rule_str = r.get("rule", "<unknown>")
        # Truncate long rules for display
        if len(rule_str) > 48:
            rule_str = rule_str[:45] + "..."
        lines.append(f"{rank:<6}{fitness:>10.4f}{complexity:>12}  {rule_str}")

    lines.append("-" * 80)
    lines.append(f"Total Pareto-optimal rules: {len(pareto_indices)}")
    lines.append("=" * 80)

    return "\n".join(lines)
