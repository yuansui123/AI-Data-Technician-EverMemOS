"""
Rule representation and population management.

Provides:
  - ``Rule`` dataclass for individual classification rules
  - ``count_complexity`` helper
  - ``RulePopulation`` class managing a set of rules for a single pattern,
    including evaluation, numeric evolution, Pareto front tracking,
    concept library, and persistence.
"""

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from tools.lasr.evaluation import evaluate_rule
from tools.lasr.pareto import extract_pareto_front, pareto_summary


# ---------------------------------------------------------------------------
# Rule dataclass
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    """A single boolean classification rule with evaluation metadata."""

    rule: str                       # Python boolean expression
    fitness: float = 0.0
    complexity: int = 1
    generation: int = 0
    origin: str = "manual"          # "manual", "numeric_mutate", "llm_mutate", "llm_crossover"
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON persistence."""
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Rule":
        """Reconstruct a Rule from a dict."""
        return Rule(
            rule=d["rule"],
            fitness=d.get("fitness", 0.0),
            complexity=d.get("complexity", 1),
            generation=d.get("generation", 0),
            origin=d.get("origin", "manual"),
            true_positives=d.get("true_positives", 0),
            false_positives=d.get("false_positives", 0),
            true_negatives=d.get("true_negatives", 0),
            false_negatives=d.get("false_negatives", 0),
        )

    def __repr__(self) -> str:
        trunc = self.rule if len(self.rule) <= 60 else self.rule[:57] + "..."
        return (
            f"Rule(fitness={self.fitness:.4f}, complexity={self.complexity}, "
            f"origin={self.origin!r}, rule={trunc!r})"
        )


# ---------------------------------------------------------------------------
# Complexity helper
# ---------------------------------------------------------------------------

_OPERATOR_RE = re.compile(r"\b(and|or|AND|OR)\b")


def count_complexity(rule_str: str) -> int:
    """Count the number of AND/OR operators in a rule string, plus 1.

    A single predicate (no operators) has complexity 1.
    ``"a > 1 AND b < 2"`` has complexity 2.
    ``"a > 1 AND b < 2 OR c > 3"`` has complexity 3.
    """
    return len(_OPERATOR_RE.findall(rule_str)) + 1


# ---------------------------------------------------------------------------
# RulePopulation
# ---------------------------------------------------------------------------

class RulePopulation:
    """Manage a population of rules for a single pattern.

    The population has a maximum size.  When the limit is exceeded, the
    population is pruned to keep all Pareto-optimal rules plus the
    highest-fitness rules up to *max_size*.
    """

    def __init__(self, pattern_name: str, max_size: int = 50):
        self.pattern_name = pattern_name
        self.max_size = max_size
        self.rules: List[Rule] = []
        self.concept_library: List[str] = []
        self._generation = 0

    # ---- Adding rules ----

    def add_rule(self, rule: Rule) -> None:
        """Add a single rule, computing complexity if not set."""
        if rule.complexity <= 0:
            rule.complexity = count_complexity(rule.rule)
        # Deduplicate: skip if an identical rule string already exists
        existing_strs = {r.rule for r in self.rules}
        if rule.rule not in existing_strs:
            self.rules.append(rule)
            self._prune()

    def add_rules(self, rules: List[Rule]) -> None:
        """Add multiple rules at once, then prune."""
        existing_strs = {r.rule for r in self.rules}
        for rule in rules:
            if rule.complexity <= 0:
                rule.complexity = count_complexity(rule.rule)
            if rule.rule not in existing_strs:
                self.rules.append(rule)
                existing_strs.add(rule.rule)
        self._prune()

    # ---- Pruning ----

    def _prune(self) -> None:
        """Keep Pareto-optimal rules + top fitness rules up to *max_size*."""
        if len(self.rules) <= self.max_size:
            return

        # Get Pareto front indices
        rule_dicts = [r.to_dict() for r in self.rules]
        pareto_idx = set(extract_pareto_front(rule_dicts))

        # Sort non-Pareto rules by fitness descending
        non_pareto = [
            (i, self.rules[i]) for i in range(len(self.rules))
            if i not in pareto_idx
        ]
        non_pareto.sort(key=lambda x: -x[1].fitness)

        # Keep all Pareto rules + top non-Pareto up to max_size
        remaining_slots = self.max_size - len(pareto_idx)
        keep_indices = set(pareto_idx)

        if remaining_slots > 0:
            for i, _rule in non_pareto[:remaining_slots]:
                keep_indices.add(i)

        self.rules = [self.rules[i] for i in sorted(keep_indices)]

    # ---- Evaluation ----

    def evaluate_all(
        self,
        exemplar_features: List[Dict[str, float]],
        exemplar_labels: List[bool],
        embedding_sims: Optional[List[float]] = None,
    ) -> None:
        """Re-evaluate every rule in the population and update metrics."""
        for rule in self.rules:
            metrics = evaluate_rule(
                rule.rule,
                exemplar_features,
                exemplar_labels,
                embedding_sims=embedding_sims,
            )
            rule.fitness = metrics["fitness"]
            rule.true_positives = metrics["tp"]
            rule.false_positives = metrics["fp"]
            rule.true_negatives = metrics["tn"]
            rule.false_negatives = metrics["fn"]
            rule.complexity = count_complexity(rule.rule)

    # ---- Numeric evolution ----

    def numeric_evolve(
        self,
        exemplar_features: List[Dict[str, float]],
        exemplar_labels: List[bool],
        embedding_sims: Optional[List[float]] = None,
        top_k: int = 5,
    ) -> List[Rule]:
        """Run numeric mutation on the top-k rules and add offspring.

        Returns the list of new rules that were actually added (post-dedup).
        """
        from tools.lasr.evolution import numeric_mutate

        self._generation += 1

        # Sort by fitness and pick top-k
        sorted_rules = sorted(self.rules, key=lambda r: -r.fitness)
        parents = sorted_rules[:top_k]

        all_new: List[Rule] = []
        for parent in parents:
            variants = numeric_mutate(
                parent,
                exemplar_features,
                exemplar_labels,
                embedding_sims=embedding_sims,
            )
            for v in variants:
                v.generation = self._generation
            all_new.extend(variants)

        # Add to population (dedup + prune happens inside)
        before = len(self.rules)
        self.add_rules(all_new)
        actually_added = self.rules[before:] if len(self.rules) > before else []

        return actually_added

    # ---- Pareto front ----

    def get_pareto_front(self) -> List[Rule]:
        """Return the Pareto-optimal rules."""
        if not self.rules:
            return []
        rule_dicts = [r.to_dict() for r in self.rules]
        pareto_idx = extract_pareto_front(rule_dicts)
        return [self.rules[i] for i in pareto_idx]

    # ---- Best rule ----

    def best_rule(self) -> Optional[Rule]:
        """Return the highest-fitness rule, or None if the population is empty."""
        if not self.rules:
            return None
        return max(self.rules, key=lambda r: r.fitness)

    # ---- Concept library ----

    def add_concept(self, concept: str) -> None:
        """Add a named concept to the library (de-duplicated)."""
        if concept not in self.concept_library:
            self.concept_library.append(concept)

    # ---- Summary ----

    def summary(self) -> str:
        """Human-readable population summary."""
        lines = [
            f"RulePopulation: {self.pattern_name}",
            f"  Rules:      {len(self.rules)} / {self.max_size}",
            f"  Generation: {self._generation}",
            f"  Concepts:   {len(self.concept_library)}",
        ]

        if self.rules:
            best = self.best_rule()
            pareto = self.get_pareto_front()
            lines.append(f"  Pareto size: {len(pareto)}")
            if best:
                lines.append(f"  Best fitness: {best.fitness:.4f}")
                lines.append(f"  Best rule:    {best.rule}")

            # Pareto table
            rule_dicts = [r.to_dict() for r in self.rules]
            pareto_idx = extract_pareto_front(rule_dicts)
            lines.append("")
            lines.append(pareto_summary(rule_dicts, pareto_idx))
        else:
            lines.append("  (empty)")

        return "\n".join(lines)

    # ---- Persistence ----

    def save(self, path: str) -> None:
        """Save the population to a JSON file."""
        data = {
            "pattern_name": self.pattern_name,
            "max_size": self.max_size,
            "generation": self._generation,
            "concept_library": self.concept_library,
            "rules": [r.to_dict() for r in self.rules],
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "RulePopulation":
        """Load a population from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)

        pop = cls(
            pattern_name=data.get("pattern_name", "unknown"),
            max_size=data.get("max_size", 50),
        )
        pop._generation = data.get("generation", 0)
        pop.concept_library = data.get("concept_library", [])
        pop.rules = [Rule.from_dict(d) for d in data.get("rules", [])]

        return pop
