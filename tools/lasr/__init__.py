"""
v2 AI Data Technician -- LASR optimization engine.

Re-exports the public API from sub-modules so callers can do::

    from tools.lasr import Rule, RulePopulation, evaluate_rule, ...
"""

from tools.lasr.population import Rule, RulePopulation, count_complexity
from tools.lasr.evaluation import evaluate_rule
from tools.lasr.evolution import (
    numeric_mutate,
    format_mutation_prompt,
    format_crossover_prompt,
    format_concept_abstraction_prompt,
    format_concept_evolution_prompt,
)
from tools.lasr.pareto import extract_pareto_front, select_by_threshold, pareto_summary
from tools.lasr.sampling import (
    select_smart_samples,
    score_uncertainty,
    score_exploration,
)
