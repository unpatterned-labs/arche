---
applyTo:
  - "packages/arche-core/src/**/*.py"
  - "packages/arche-core/tests/**/*.py"
---

# Python style (`arche-core`)

## Language baseline
- Python 3.11+ — use modern syntax (`match`, structural patterns, `X | Y` unions, `Self`).
- `from __future__ import annotations` at the top of every module. Avoid quoted type hints.
- Type-hint everything that is public. `Any` is allowed only for genuine container-of-unknown payloads (e.g. user-supplied `metadata: dict[str, Any]`).
- Use `TYPE_CHECKING` for imports that are only used in type hints (see `arche/__init__.py` for the canonical pattern with `PlaceResolver`).

## Imports
- Top-of-file imports for everything used at module load.
- Function-local imports are the standard for **lazy loading**:
  - Optional extras (`pymupdf`, `presidio`, `splink`, `docling`) — import inside the function and raise an actionable error if the extra is missing.
  - Cross-layer imports that would otherwise create cycles (e.g. `arche.workflow.pipeline` importing from `arche.audit`).
  - Anything that takes >50ms to import (e.g. `gliner`, `onnxruntime`).
- Standard library first, then third-party, then `arche.*` — `ruff` enforces this.

## Naming
- Modules: `snake_case`. Private modules prefixed with `_` (e.g. `_matcher.py`, `_review.py`) are internal — do not document them in the README and do not surface them on `from arche import *`.
- Classes: `PascalCase`. Functions and variables: `snake_case`.
- Public data containers prefer `@dataclass` over plain classes; pydantic `BaseModel` only when validation/OpenAPI schema is the explicit goal (see `arche.models`).

## Error handling
- Errors are actionable: tell the caller what went wrong **and how to fix it**.
  ```python
  raise ImportError(
      "GliNER backend requires the [detect] extra. "
      "Install with: pip install arche-core[detect]"
  )
  ```
- Never silently swallow. If you must continue on failure, `_log.warning(...)` with the exception and a one-line reason.
- Use the package logger: `_log = logging.getLogger("arche")` (or `logging.getLogger("arche.<submodule>")` for noisy subsystems).
- Deprecation warnings go through `warnings.warn(..., DeprecationWarning, stacklevel=2)`. The v0.1 shim uses this; follow that pattern.

## Public surface discipline
- A function or class is **public** if it appears in `arche.__init__.__all__` or in a submodule's `__all__`.
- Public functions get a complete docstring with: one-line summary, examples, parameter docstring, return docstring, raised exceptions.
- Private helpers (`_foo`) get a one-line docstring at most. No multi-page docstrings on internals.

## Performance
- Cold-import time target: <1000 ms (`NFR-PERF-1`). Lazy-load anything heavy.
- The `_LAZY` dict in `arche/__init__.py` is how v0.1 names stay importable without paying the import cost. Use the same pattern for any new optional-extra-gated surface.

## Style nitpicks
- British or American English is fine, but be consistent within a file.
- No decorative `# ====` separators unless the file is genuinely sectioned (e.g. `__init__.py`).
- Keep comment density low — explain *why*, never *what*. The code says what.
- `print()` for CLI output only. Everything else is `_log.{debug,info,warning,error}`.

## When in doubt
- Read 2 neighbouring modules in the same layer and match their style.
- Karpathy: surgical changes, no speculative abstractions.
