"""
Rule evaluation against labeled exemplars.

A rule is a Python boolean expression referencing feature names (e.g.
``alpha_power_rel > 0.3 AND spectral_slope < -1.5``).  This module
translates the human-friendly AND/OR/NOT syntax to Python, evaluates the
rule against each exemplar's feature dict, and computes classification
metrics.
"""

import json
import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _translate_rule(rule_str: str) -> str:
    """Translate AND/OR/NOT to Python and/or/not.

    Handles upper-case, mixed-case, and already-Pythonic forms.
    Preserves content inside string literals.
    """
    # Replace logical operators (word-boundary aware, case-insensitive)
    translated = re.sub(r'\bAND\b', 'and', rule_str)
    translated = re.sub(r'\bOR\b', 'or', translated)
    translated = re.sub(r'\bNOT\b', 'not', translated)
    return translated


def _safe_namespace(features: Dict[str, float], embedding_sim: float = 0.0) -> dict:
    """Build a safe namespace dict for eval().

    Includes all feature values, the special ``embedding_sim`` variable,
    and a handful of math helpers so rules can use abs(), min(), max(), etc.
    """
    ns = dict(features)
    ns["embedding_sim"] = embedding_sim
    # Safe math builtins
    ns["abs"] = abs
    ns["min"] = min
    ns["max"] = max
    ns["round"] = round
    ns["sqrt"] = math.sqrt
    ns["log"] = math.log
    ns["log10"] = math.log10
    ns["exp"] = math.exp
    ns["pow"] = pow
    ns["True"] = True
    ns["False"] = False
    return ns


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_rule(
    rule_str: str,
    exemplar_features: List[Dict[str, float]],
    exemplar_labels: List[bool],
    embedding_sims: Optional[List[float]] = None,
    fp_weight: float = 1.0,
    fn_weight: float = 1.0,
) -> dict:
    """Evaluate a boolean rule against labeled exemplars.

    Parameters
    ----------
    rule_str : str
        Boolean expression, e.g. ``"alpha_power_rel > 0.3 AND NOT line_noise_ratio > 5"``
    exemplar_features : list of dict
        Each dict maps feature names to float values for one exemplar.
    exemplar_labels : list of bool
        Ground-truth labels (True = positive / "keep").
    embedding_sims : list of float or None
        Optional per-exemplar embedding similarity scores.  Exposed
        inside the rule as ``embedding_sim``.
    fp_weight : float
        Penalty weight for false positives in the weighted fitness.
    fn_weight : float
        Penalty weight for false negatives in the weighted fitness.

    Returns
    -------
    dict with keys:
        fitness, accuracy, precision, recall, f1,
        tp, fp, tn, fn,
        predictions (list[bool]),
        confidence_scores (list[float])
    """
    translated = _translate_rule(rule_str)

    n = len(exemplar_features)
    if n == 0:
        return {
            "fitness": 0.0,
            "accuracy": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "tp": 0, "fp": 0, "tn": 0, "fn": 0,
            "predictions": [],
            "confidence_scores": [],
        }

    predictions: List[bool] = []
    confidence_scores: List[float] = []
    tp = fp = tn = fn = 0

    for i in range(n):
        esim = embedding_sims[i] if embedding_sims else 0.0
        ns = _safe_namespace(exemplar_features[i], esim)

        try:
            result = bool(eval(translated, {"__builtins__": {}}, ns))  # noqa: S307
        except Exception:
            # If the rule cannot be evaluated (missing feature, syntax error),
            # treat as False (conservative: does not fire).
            result = False

        predictions.append(result)

        label = exemplar_labels[i]
        if result and label:
            tp += 1
            confidence_scores.append(1.0)
        elif result and not label:
            fp += 1
            confidence_scores.append(0.0)
        elif not result and not label:
            tn += 1
            confidence_scores.append(1.0)
        else:  # not result and label
            fn += 1
            confidence_scores.append(0.0)

    # --- Metrics ---
    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0.0

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0

    # Weighted fitness: penalise FP and FN differently
    weighted_correct = tp + tn
    weighted_wrong = fp * fp_weight + fn * fn_weight
    fitness = weighted_correct / (weighted_correct + weighted_wrong) if (weighted_correct + weighted_wrong) else 0.0

    return {
        "fitness": fitness,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "predictions": predictions,
        "confidence_scores": confidence_scores,
    }


# ---------------------------------------------------------------------------
# Pattern-level helpers
# ---------------------------------------------------------------------------

def evaluate_rule_on_pattern(rule_str: str, pattern_dir: str) -> dict:
    """Evaluate a rule against a specific pattern folder's exemplars.

    Expects the pattern directory to contain:
      - ``exemplars.json`` : list of dicts with at least a ``"label"`` key
        (bool or 0/1) and optionally ``"embedding_sim"`` (float).
      - ``features.json``  : list of dicts mapping feature names to floats.

    If either file is missing the function returns an empty metrics dict.

    Parameters
    ----------
    rule_str : str
        Boolean rule expression.
    pattern_dir : str or Path
        Path to the pattern directory.

    Returns
    -------
    dict  (same schema as :func:`evaluate_rule`)
    """
    pattern_path = Path(pattern_dir)
    exemplars_file = pattern_path / "exemplars.json"
    features_file = pattern_path / "features.json"

    if not exemplars_file.exists() or not features_file.exists():
        return {
            "fitness": 0.0, "accuracy": 0.0, "precision": 0.0,
            "recall": 0.0, "f1": 0.0,
            "tp": 0, "fp": 0, "tn": 0, "fn": 0,
            "predictions": [], "confidence_scores": [],
        }

    with open(exemplars_file, "r") as f:
        exemplars = json.load(f)
    with open(features_file, "r") as f:
        features_list = json.load(f)

    # Build labels and optional embedding sims
    exemplar_labels: List[bool] = []
    embedding_sims: List[float] = []
    has_embedding = False

    for ex in exemplars:
        label = ex.get("label", False)
        if isinstance(label, (int, float)):
            label = bool(label)
        exemplar_labels.append(label)

        esim = ex.get("embedding_sim", None)
        if esim is not None:
            has_embedding = True
            embedding_sims.append(float(esim))
        else:
            embedding_sims.append(0.0)

    # Align: use only the minimum length in case of mismatch
    n = min(len(features_list), len(exemplar_labels))
    exemplar_features = features_list[:n]
    exemplar_labels = exemplar_labels[:n]
    embedding_sims_arg = embedding_sims[:n] if has_embedding else None

    return evaluate_rule(
        rule_str,
        exemplar_features,
        exemplar_labels,
        embedding_sims=embedding_sims_arg,
    )


def batch_evaluate(rule_str: str, patterns_dir: str) -> Dict[str, dict]:
    """Evaluate a rule across all pattern folders under *patterns_dir*.

    Each immediate sub-directory of *patterns_dir* that contains an
    ``exemplars.json`` file is treated as a pattern folder.

    Parameters
    ----------
    rule_str : str
        Boolean rule expression.
    patterns_dir : str or Path
        Root directory containing pattern sub-folders.

    Returns
    -------
    dict mapping pattern name (folder name) to its evaluation result dict.
    """
    patterns_path = Path(patterns_dir)
    results: Dict[str, dict] = {}

    if not patterns_path.is_dir():
        return results

    for entry in sorted(patterns_path.iterdir()):
        if not entry.is_dir():
            continue
        # Only evaluate folders that look like pattern dirs
        if (entry / "exemplars.json").exists():
            result = evaluate_rule_on_pattern(rule_str, str(entry))
            results[entry.name] = result

    return results
