"""Local pandas execution sandbox — `execute_pandas_code` tool (spec/agent.md).

This module is the single most safety-critical piece of the CSV Insight
Agent. It does two jobs:

1. **Execute** LLM-generated code of the shape ``def analyze(df: pd.DataFrame)
   -> dict`` in a restricted namespace, with no filesystem/network/OS access
   and a wall-clock timeout, so a buggy or malicious generation can't do
   anything but crash or time out.
2. **Sanitize** the result via `sanitize_result`, the deterministic Privacy
   Boundary classifier (`spec/architecture.md` → Privacy Boundary). This is
   the ONLY function that decides what is allowed to travel from the local
   sandbox into a Gemini prompt. `execution_full_result` (the untouched
   output of `analyze`) must NEVER be passed to `LLMClient` — only the
   output of `sanitize_result` (`execution_result`) may be.
"""

from __future__ import annotations

import concurrent.futures
import math

import numpy as np
import pandas as pd

# Aggregates up to this many rows/keys are considered "small enough" to be
# safe to send to the LLM as-is (spec/architecture.md Privacy Boundary: "≤ 20
# grouped rows").
MAX_AGGREGATE_ROWS = 20

DEFAULT_TIMEOUT_SECONDS = 25.0

# Tokens that must never appear in LLM-generated analysis code. This is a
# defense-in-depth layer on top of the restricted execution namespace below
# (which already omits `__import__`, `open`, etc. from builtins) — a static
# textual reject list catches attempts before we even exec the code.
_FORBIDDEN_TOKENS = (
    "import ",
    "__import__",
    "open(",
    "os.",
    "sys.",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "eval(",
    "exec(",
    "compile(",
    "globals(",
    "locals(",
    "__builtins__",
    "__class__",
    "__bases__",
    "__subclasses__",
    "getattr(",
    "setattr(",
    "delattr(",
    "input(",
)

# Deliberately small — only what pandas analysis code legitimately needs.
_SAFE_BUILTINS = {
    "len": len,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "sorted": sorted,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "enumerate": enumerate,
    "zip": zip,
    "abs": abs,
    "round": round,
    "isinstance": isinstance,
    "True": True,
    "False": False,
    "None": None,
}


class SandboxError(Exception):
    """Raised for sandbox-level failures (rejected code, timeout, bad shape)."""


def _static_guard(code: str) -> None:
    lowered = code
    for token in _FORBIDDEN_TOKENS:
        if token in lowered:
            raise SandboxError(f"Generated code uses a forbidden construct: {token.strip()!r}")


def _run(code: str, df: pd.DataFrame) -> dict:
    _static_guard(code)

    namespace: dict = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "np": np}
    try:
        exec(code, namespace)  # noqa: S102 - restricted namespace by design
    except Exception as exc:  # noqa: BLE001
        raise SandboxError(f"Code failed to compile/define: {exc}") from exc

    analyze = namespace.get("analyze")
    if not callable(analyze):
        raise SandboxError("Generated code must define a function named `analyze(df)`.")

    result = analyze(df)
    if not isinstance(result, dict):
        raise SandboxError("`analyze(df)` must return a dict.")
    return result


def run_user_code(code: str, df: pd.DataFrame, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Executes `code` (must define `analyze(df) -> dict`) against `df`.

    Returns ``{"full_result": dict | None, "result": dict | None, "error": str | None}``.
    `full_result` is the raw, potentially row-level output — local/DB/frontend
    only. `result` is the output of `sanitize_result(full_result)` — the only
    field ever allowed into a Gemini prompt. Exactly one of
    (`full_result`/`result`) or `error` is set.
    """
    if df is None:
        return {"full_result": None, "result": None, "error": "No dataset loaded for this run."}

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run, code, df)
        try:
            full_result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return {
                "full_result": None,
                "result": None,
                "error": f"Code execution exceeded the {timeout:.0f}s time limit.",
            }
        except SandboxError as exc:
            return {"full_result": None, "result": None, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - any runtime error from user code
            return {"full_result": None, "result": None, "error": f"Execution error: {exc}"}

    return {"full_result": full_result, "result": sanitize_result(full_result), "error": None}


# ---------------------------------------------------------------------------
# Privacy Boundary classifier
# ---------------------------------------------------------------------------


def _is_scalar(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (np.generic,)):
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _classify_value(value):
    """Returns the sanitized version of a single result value.

    Aggregates (scalars, small flat dicts of ≤ MAX_AGGREGATE_ROWS
    scalar-valued entries — i.e. the shape produced by `series.to_dict()`
    from a `groupby`/`agg` reduction — or small flat lists of ≤
    MAX_AGGREGATE_ROWS scalars) pass through unchanged. Anything that is, or
    contains, multi-field records — a list/tuple of dicts, or a DataFrame —
    is ALWAYS reduced to shape/column metadata only, regardless of row
    count: row count alone cannot distinguish a safe aggregation result from
    a row-level record dump, so record-shaped values never pass through
    literal values. Anything larger than the aggregate threshold is also
    reduced to shape/dtype metadata only. No literal values survive for
    anything not covered by the two safe shapes above.
    """
    if _is_scalar(value):
        return value

    if isinstance(value, pd.DataFrame):
        # A DataFrame is a multi-field record structure (row-level data) by
        # construction — it must NEVER pass through with literal values,
        # regardless of row count (see `_classify_value` list-of-dict rule).
        return {"_type": "dataframe", "shape": list(value.shape), "columns": list(map(str, value.columns))}

    if isinstance(value, pd.Series):
        if len(value) <= MAX_AGGREGATE_ROWS:
            return {str(k): v for k, v in value.to_dict().items()}
        return {"_type": "series", "length": int(len(value)), "dtype": str(value.dtype)}

    if isinstance(value, dict):
        if len(value) <= MAX_AGGREGATE_ROWS and all(_is_scalar(v) for v in value.values()):
            return value
        return {"_type": "dict", "keys_count": len(value)}

    if isinstance(value, (list, tuple)):
        # A list of dict items is a multi-field record structure — i.e. it
        # represents row-level data (a slice/sample of original rows), even
        # when small. This must NEVER pass through with literal values,
        # regardless of length: row count alone cannot distinguish a
        # groupby/aggregation result from a dump of individual records, and
        # a small dataset makes that collision easy to hit. Only flat lists
        # of scalars (no column/identity semantics) may pass through.
        has_any_dict_item = any(isinstance(item, dict) for item in value)
        is_small_scalar_list = (
            not has_any_dict_item
            and len(value) <= MAX_AGGREGATE_ROWS
            and all(_is_scalar(item) for item in value)
        )
        if is_small_scalar_list:
            return list(value)
        sample = value[0] if value else None
        columns = list(sample.keys()) if isinstance(sample, dict) else None
        return {
            "_type": "list",
            "length": len(value),
            "columns": columns,
            "item_type": type(sample).__name__ if sample is not None else None,
        }

    # Anything else (custom objects, nested arrays, etc.) — type name only.
    return {"_type": type(value).__name__}


def sanitize_result(full_result: dict | None) -> dict | None:
    """The Privacy Boundary classifier — the ONLY function allowed to
    produce a payload that may be sent to Gemini from execution output.

    Never returns literal cell values for row-level/large results — only
    shape/dtype/column-name metadata. Small (`<= 20` row) aggregates pass
    through their actual values, matching `spec/architecture.md`'s
    definition of what's safe.
    """
    if full_result is None:
        return None
    if not isinstance(full_result, dict):
        return {"_type": type(full_result).__name__}
    return {key: _classify_value(val) for key, val in full_result.items()}
