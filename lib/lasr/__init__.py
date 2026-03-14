"""
v2 AI Data Technician -- LASR optimization engine.

Re-exports the public API from sub-modules so callers can do::

    from lib.lasr import Rule, RulePopulation, evaluate_rule, ...
"""

from lib.lasr.population import Rule, RulePopulation, count_complexity
from lib.lasr.evaluation import evaluate_rule
from lib.lasr.evolution import (
    numeric_mutate,
    format_mutation_prompt,
    format_crossover_prompt,
    format_concept_abstraction_prompt,
    format_concept_evolution_prompt,
)
from lib.lasr.pareto import extract_pareto_front, select_by_threshold, pareto_summary
from lib.lasr.sampling import (
    select_smart_samples,
    score_uncertainty,
    score_exploration,
)
