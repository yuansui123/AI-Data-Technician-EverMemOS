"""Sandbox policy helpers for path guards and runtime defaults."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

VALID_SANDBOX_BACKENDS = {"local", "docker"}


@dataclass(frozen=True)
class SandboxRuntimePolicy:
    """Runtime constraints shared by sandbox backends."""

    backend: str
    command_timeout_seconds: int = 120
    network_enabled: bool = False
    cpus: str = "1"
    memory: str = "2g"
    pids_limit: int = 256
    docker_image: str = "python:3.11-slim"


def validate_backend(name: str) -> str:
    backend = (name or "local").strip().lower()
    if backend not in VALID_SANDBOX_BACKENDS:
        allowed = ", ".join(sorted(VALID_SANDBOX_BACKENDS))
        raise ValueError(f"Invalid sandbox backend {name!r}. Expected one of: {allowed}")
    return backend


def normalize_allowed_roots(
    project_dir: str | Path,
    allowed_roots: Iterable[str | Path] | None = None,
) -> tuple[Path, ...]:
    roots = [Path(project_dir).resolve()]
    if allowed_roots:
        roots.extend(Path(root).resolve() for root in allowed_roots)
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return tuple(deduped)


def is_path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_path_in_roots(path: Path, allowed_roots: Iterable[Path], label: str = "path") -> str | None:
    resolved = path.resolve()
    roots = [root.resolve() for root in allowed_roots]
    if any(is_path_within(resolved, root) for root in roots):
        return None
    root_text = ", ".join(str(root) for root in roots)
    return f"Refused: {label} {resolved} is outside allowed roots: {root_text}"


def resolve_and_validate_cwd(
    cwd: str | Path | None,
    default_cwd: str | Path,
    allowed_roots: Iterable[Path],
) -> tuple[Path | None, str | None]:
    if cwd is None:
        candidate = Path(default_cwd)
    else:
        cwd_path = Path(cwd)
        candidate = cwd_path if cwd_path.is_absolute() else (Path(default_cwd) / cwd_path)
    resolved = candidate.resolve()
    error = validate_path_in_roots(resolved, allowed_roots, label="cwd")
    if error:
        return None, error
    return resolved, None


def build_session_id(scope: str, parent_session_id: str | None = None) -> str:
    now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    salt = uuid4().hex[:8]
    prefix = "".join(ch for ch in scope if ch.isalnum() or ch in ("-", "_")) or "sandbox"
    if parent_session_id:
        parent = "".join(ch for ch in str(parent_session_id) if ch.isalnum() or ch in ("-", "_"))[:20]
        return f"{prefix}_{parent}_{now}_{salt}"
    return f"{prefix}_{now}_{salt}"


def build_session_tmp_dir(project_dir: str | Path, session_id: str) -> Path:
    tmp_dir = Path(project_dir).resolve() / "tmp" / f"session_{session_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir
