"""
Smart sampling strategy for active-learning signal selection.

Combines three scoring strategies and blends them with round-adaptive
weights so that early rounds explore broadly while later rounds exploit
rule uncertainty to fill in classification boundaries.

Adapted from v1 active_learning.py with new scoring functions and a
cleaner round-adaptive mixing schedule.
"""

import math
import random
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------

def score_uncertainty(
    features: Dict[str, float],
    rules: list,
    embedding_sim: float = 0.0,
) -> float:
    """Score how uncertain the current rule population is about a signal.

    Evaluates every rule in *rules* against *features* and measures the
    fraction of rules that disagree with the majority vote.

    Parameters
    ----------
    features : dict
        Feature-name -> value mapping for one signal.
    rules : list
        List of Rule objects (each has a ``.rule`` attribute with a
        boolean expression string).
    embedding_sim : float
        Embedding similarity score for this signal.

    Returns
    -------
    float in [0, 1] where 1 = maximum uncertainty (50/50 split).
    """
    if not rules:
        return 1.0  # No rules => total uncertainty

    from lib.lasr.evaluation import _translate_rule, _safe_namespace

    votes: List[bool] = []
    ns = _safe_namespace(features, embedding_sim)

    for rule_obj in rules:
        rule_str = rule_obj.rule if hasattr(rule_obj, "rule") else str(rule_obj)
        translated = _translate_rule(rule_str)
        try:
            result = bool(eval(translated, {"__builtins__": {}}, ns))  # noqa: S307
        except Exception:
            continue  # skip broken rules
        votes.append(result)

    if not votes:
        return 1.0

    positive_frac = sum(votes) / len(votes)
    # Disagreement: 0 when unanimous, 1 when 50/50
    disagreement = 1.0 - abs(2.0 * positive_frac - 1.0)
    return disagreement


def score_exploration(
    features: Dict[str, float],
    known_cluster_centers: Optional[np.ndarray] = None,
    feature_names: Optional[List[str]] = None,
) -> float:
    """Score how far a signal is from all known cluster centres.

    Computes the minimum Euclidean distance from the signal's feature
    vector to every known cluster centre, then normalises by the median
    distance across all centres.

    Parameters
    ----------
    features : dict
        Feature-name -> value mapping.
    known_cluster_centers : ndarray of shape (k, d) or None
        Each row is a cluster centre in the same feature space.
    feature_names : list of str or None
        Ordered feature names matching the columns of *known_cluster_centers*.
        If None, sorted keys of *features* are used.

    Returns
    -------
    float in [0, 1] (clamped).  1 = far from any cluster.
    """
    if known_cluster_centers is None or len(known_cluster_centers) == 0:
        return 1.0  # No clusters known => everything is novel

    if feature_names is None:
        feature_names = sorted(features.keys())

    vec = np.array([features.get(fn, 0.0) for fn in feature_names], dtype=np.float64)

    # Distance to every cluster centre
    diffs = known_cluster_centers - vec  # (k, d)
    dists = np.sqrt(np.sum(diffs ** 2, axis=1))  # (k,)

    min_dist = float(np.min(dists))

    # Normalise by median pairwise distance between centres
    if len(known_cluster_centers) >= 2:
        # Compute pairwise distances between centres
        n_centres = len(known_cluster_centers)
        pairwise = []
        for i in range(n_centres):
            for j in range(i + 1, n_centres):
                pairwise.append(float(np.linalg.norm(
                    known_cluster_centers[i] - known_cluster_centers[j]
                )))
        median_dist = float(np.median(pairwise)) if pairwise else 1.0
    else:
        # Only one centre: use the distance itself as scale
        median_dist = min_dist if min_dist > 0 else 1.0

    normalised = min_dist / (median_dist + 1e-12)
    # Sigmoid-like squash into [0, 1]
    score = 1.0 - math.exp(-normalised)
    return max(0.0, min(1.0, score))


def score_surprising_keeps(
    features: Dict[str, float],
    keep_features_list: Optional[List[Dict[str, float]]] = None,
) -> float:
    """Score how unusual a signal is relative to accepted ("keep") signals.

    Uses a Mahalanobis-like distance from the empirical distribution
    (mean and standard deviation) of all previously kept signals.

    Parameters
    ----------
    features : dict
        Feature-name -> value for the candidate signal.
    keep_features_list : list of dict or None
        Feature dicts of all previously kept (positive-label) signals.

    Returns
    -------
    float in [0, 1].  1 = very unusual relative to the kept population.
    """
    if not keep_features_list or len(keep_features_list) < 2:
        return 0.5  # Not enough data to judge

    # Use features common to the candidate and the kept set
    common_keys = sorted(
        set(features.keys()) & set(keep_features_list[0].keys())
    )
    if not common_keys:
        return 0.5

    # Build matrix of kept feature vectors
    keep_matrix = np.array(
        [[kf.get(k, 0.0) for k in common_keys] for kf in keep_features_list],
        dtype=np.float64,
    )
    candidate = np.array([features.get(k, 0.0) for k in common_keys], dtype=np.float64)

    means = np.mean(keep_matrix, axis=0)
    stds = np.std(keep_matrix, axis=0)
    stds[stds < 1e-12] = 1.0  # avoid division by zero

    # Standardised distance per dimension
    z_scores = np.abs((candidate - means) / stds)
    avg_z = float(np.mean(z_scores))

    # Map to [0, 1] via sigmoid-like transform; z ~ 2 -> ~0.5
    score = 1.0 - math.exp(-avg_z / 2.0)
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Round-adaptive weights
# ---------------------------------------------------------------------------

_ROUND_WEIGHTS = {
    # round: (exploit, explore, random)
    1: (0.00, 0.85, 0.15),
    2: (0.50, 0.40, 0.10),
    3: (0.70, 0.25, 0.05),
}
_DEFAULT_WEIGHTS = (0.85, 0.15, 0.00)  # round 4+


def _get_round_weights(round_number: int) -> Tuple[float, float, float]:
    """Return (exploit_weight, explore_weight, random_weight) for the round."""
    return _ROUND_WEIGHTS.get(round_number, _DEFAULT_WEIGHTS)


# ---------------------------------------------------------------------------
# Main selection function
# ---------------------------------------------------------------------------

def select_smart_samples(
    all_features: List[Dict[str, float]],
    rules: list,
    round_number: int = 1,
    n: int = 15,
    known_cluster_centers: Optional[np.ndarray] = None,
    keep_features_list: Optional[List[Dict[str, float]]] = None,
    feature_names_list: Optional[List[str]] = None,
    embedding_sims: Optional[List[float]] = None,
) -> List[Tuple[int, float, str]]:
    """Select N signals using a round-adaptive exploitation/exploration/random mix.

    Parameters
    ----------
    all_features : list of dict
        Feature dicts for every candidate signal.
    rules : list
        Current Rule objects in the population.
    round_number : int
        Current labeling round (1-based).
    n : int
        Number of signals to select.
    known_cluster_centers : ndarray (k, d) or None
        Cluster centres for exploration scoring.
    keep_features_list : list of dict or None
        Feature dicts of previously accepted signals.
    feature_names_list : list of str or None
        Ordered feature names matching cluster centre columns.
    embedding_sims : list of float or None
        Per-signal embedding similarity scores.

    Returns
    -------
    list of (index, score, source) tuples, where *source* is one of
    ``'exploit'``, ``'explore'``, or ``'random'``.

    Round-adaptive weights
    ~~~~~~~~~~~~~~~~~~~~~~
    ===========  =========  =========  ========
    Round        Exploit    Explore    Random
    ===========  =========  =========  ========
    1            0 %        85 %       15 %
    2            50 %       40 %       10 %
    3            70 %       25 %       5 %
    4+           85 %       15 %       0 %
    ===========  =========  =========  ========
    """
    total = len(all_features)
    if total == 0:
        return []

    n = min(n, total)
    exploit_w, explore_w, random_w = _get_round_weights(round_number)

    n_exploit = int(round(n * exploit_w))
    n_explore = int(round(n * explore_w))
    n_random = n - n_exploit - n_explore  # remainder goes to random

    # Ensure non-negative counts
    if n_random < 0:
        n_explore += n_random
        n_random = 0
    if n_explore < 0:
        n_exploit += n_explore
        n_explore = 0

    selected_indices: set = set()
    results: List[Tuple[int, float, str]] = []

    # --- EXPLOIT: signals where rules are most uncertain ----
    if n_exploit > 0 and rules:
        uncertainty_scores: List[Tuple[int, float]] = []
        for i, feat in enumerate(all_features):
            esim = embedding_sims[i] if embedding_sims else 0.0
            u = score_uncertainty(feat, rules, embedding_sim=esim)
            uncertainty_scores.append((i, u))
        # Sort descending by uncertainty
        uncertainty_scores.sort(key=lambda x: -x[1])
        for idx, score in uncertainty_scores:
            if idx not in selected_indices:
                selected_indices.add(idx)
                results.append((idx, score, "exploit"))
                if len([r for r in results if r[2] == "exploit"]) >= n_exploit:
                    break

    # --- EXPLORE: signals farthest from known clusters ----
    if n_explore > 0:
        exploration_scores: List[Tuple[int, float]] = []
        for i, feat in enumerate(all_features):
            if i in selected_indices:
                continue
            e = score_exploration(
                feat,
                known_cluster_centers=known_cluster_centers,
                feature_names=feature_names_list,
            )
            # Also factor in surprise relative to kept signals
            s = score_surprising_keeps(feat, keep_features_list)
            combined = 0.6 * e + 0.4 * s
            exploration_scores.append((i, combined))
        # Sort descending by exploration score
        exploration_scores.sort(key=lambda x: -x[1])
        for idx, score in exploration_scores:
            if idx not in selected_indices:
                selected_indices.add(idx)
                results.append((idx, score, "explore"))
                if len([r for r in results if r[2] == "explore"]) >= n_explore:
                    break

    # --- RANDOM: fill remaining slots with random samples ----
    remaining_needed = n - len(results)
    if remaining_needed > 0:
        available = [i for i in range(total) if i not in selected_indices]
        if available:
            random_picks = random.sample(available, min(remaining_needed, len(available)))
            for idx in random_picks:
                selected_indices.add(idx)
                results.append((idx, 0.0, "random"))

    return results
