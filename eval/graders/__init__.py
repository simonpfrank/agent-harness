"""Code grader registry with auto-discovery, mirroring agent_harness.tools.discover_tools."""

from __future__ import annotations

import importlib.util
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import get_type_hints

from eval.types import GradeResult

logger = logging.getLogger(__name__)

CodeGrader = Callable[..., GradeResult]


def build_grader_registry() -> dict[str, CodeGrader]:
    """Build the registry of built-in code graders shipped with the framework.

    Returns:
        Registry mapping grader name to grader function.
    """
    from eval.graders.code.column_match import column_match
    from eval.graders.code.contains import contains

    return {"contains": contains, "column_match": column_match}


registry: dict[str, CodeGrader] = build_grader_registry()


def discover_code_graders(
    graders_dir: str,
    base_registry: dict[str, CodeGrader] | None = None,
) -> dict[str, CodeGrader]:
    """Discover and register code graders from a directory.

    Each `.py` file should contain one public function with type annotations
    returning `GradeResult`.

    Args:
        graders_dir: Path to directory containing grader `.py` files.
        base_registry: Registry to extend. Defaults to the module-level registry.

    Returns:
        The registry that received discovered graders.
    """
    target_registry = base_registry if base_registry is not None else registry
    path = Path(graders_dir)
    if not path.is_dir():
        return target_registry
    for py_file in sorted(path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if name.startswith("_"):
                    continue
                hints = get_type_hints(obj)
                if "return" not in hints:
                    continue
                target_registry[name] = obj
                logger.info("Registered code grader: %s from %s", name, py_file.name)
                break
        except Exception as exc:
            logger.warning("Failed to load grader from %s: %s", py_file.name, exc)
    return target_registry
