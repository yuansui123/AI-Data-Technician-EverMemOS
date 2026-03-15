"""Workflows — lazy-imported to avoid pulling in v4cedars deps at startup."""

__all__ = [
    "explore_dataset",
    "ingest_documents",
    "optimize_pattern",
    "teach_session",
    "review_results",
    "apply_rules",
]

_MODULES = {
    "explore_dataset": "workflows.explore_dataset",
    "ingest_documents": "workflows.ingest_documents",
    "optimize_pattern": "workflows.optimize_pattern",
    "teach_session": "workflows.teach_session",
    "review_results": "workflows.review_results",
    "apply_rules": "workflows.apply_rules",
}


def __getattr__(name: str):
    if name in _MODULES:
        from importlib import import_module
        mod = import_module(_MODULES[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
