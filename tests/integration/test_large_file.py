"""Phase 2 large-file correctness + latency test (spec/roadmap.md Phase 2 gate).

Proves the pipeline holds its answer quality and the 30-second budget on a
large (~90MB / ~500k-row) CSV, computing the aggregate over the FULL dataset
rather than a sample. Runs the real stack: FastAPI app, real SQLite DB, and
the real Gemini API — no mocks. Requires AGENT_GEMINI_API_KEY (or
AGENT_ANTHROPIC_API_KEY) in .env; skipped otherwise.

The large CSV is generated at setup via ``scripts/make_large_sample.py`` into
pytest's ``tmp_path`` (outside the repo, auto-removed after the test), and the
upload directory is likewise redirected into ``tmp_path`` so nothing lands in
the repo working tree. See ``.gitignore`` for the belt-and-suspenders entries.
"""
from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path

import pandas as pd
import pytest

# Row count large enough to produce a ~90MB file and a materially different
# aggregate between the full dataset and a 1,000-row head sample.
_ROWS = 500_000
_SEED = 42
_SAMPLE_ROWS = 1_000

# The ask-a-question run (post -> terminal) must complete within this budget.
_RUN_BUDGET_S = 30.0

# Poll settings for the background run. The poll ceiling is deliberately
# higher than the asserted budget so we can *measure* an over-budget run and
# fail on the real number rather than time out ambiguously.
_POLL_TIMEOUT_S = 90
_POLL_INTERVAL_S = 0.5

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "make_large_sample.py"

_QUESTION = (
    "What is the total sum of the 'amount' column across the entire dataset, "
    "ignoring missing values? Report the total as a single number."
)


def _load_make_large_sample():
    """Import scripts/make_large_sample.py by path (it is not an installed pkg)."""
    spec = importlib.util.spec_from_file_location("make_large_sample", _SCRIPT_PATH)
    assert spec and spec.loader, f"Could not load generator at {_SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def large_csv(tmp_path):
    """Generate the ~90MB sample CSV via the provided generator script.

    Written under tmp_path so it is removed automatically after the test and
    never touches the repo working tree.
    """
    gen = _load_make_large_sample()
    out_path = tmp_path / "large_sample.csv"
    df = gen.build_dataframe(rows=_ROWS, seed=_SEED)
    df.to_csv(out_path, index=False)
    assert out_path.exists()
    size_mb = out_path.stat().st_size / (1024 * 1024)
    # Sanity: this must be a genuinely large file, not a token stub.
    assert size_mb > 50, f"Generated file is only {size_mb:.1f}MB; expected ~90MB"
    yield out_path
    out_path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path, monkeypatch):
    """Keep the uploaded copy inside tmp_path, not the repo's ./data/uploads."""
    monkeypatch.setenv("AGENT_UPLOAD_DIR", str(tmp_path / "uploads"))
    # Ensure the 90MB upload is not rejected by the size cap.
    monkeypatch.setenv("AGENT_MAX_UPLOAD_MB", "200")
    yield


def _poll_run(api_client, run_id: str) -> tuple[dict, float]:
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    start = time.monotonic()
    last = None
    while time.monotonic() < deadline:
        r = api_client.get(f"/runs/{run_id}")
        assert r.status_code == 200, r.text
        last = r.json()["data"]
        if last["status"] not in ("pending", "running"):
            return last, time.monotonic() - start
        time.sleep(_POLL_INTERVAL_S)
    raise AssertionError(
        f"Run {run_id} did not reach a terminal status within {_POLL_TIMEOUT_S}s: {last}"
    )


def _collect_numeric_candidates(final: dict) -> list[float]:
    """Every numeric value the agent surfaced, from structured fields and text."""
    candidates: list[float] = []

    def _maybe_add(value) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            candidates.append(float(value))
        elif isinstance(value, str):
            # Strip currency/thousands separators, keep sign + decimals.
            for token in re.findall(r"-?\d[\d,]*\.?\d*", value):
                cleaned = token.replace(",", "")
                try:
                    candidates.append(float(cleaned))
                except ValueError:
                    pass

    for v in (final.get("key_numbers") or {}).values():
        _maybe_add(v)

    for row in final.get("table_data") or []:
        if isinstance(row, dict):
            for v in row.values():
                _maybe_add(v)

    _maybe_add(final.get("answer_text") or "")
    return candidates


def test_large_file_full_dataset_aggregate_within_budget(
    api_client, large_csv, _require_llm_key
):
    """Upload a ~90MB CSV, ask a real aggregation question end-to-end, and
    prove (a) it completes under the 30s budget and (b) the answer reflects
    the FULL dataset, not a 1,000-row sample."""

    # --- Ground truth: full-file vs 1,000-row-sample aggregate ---
    full_df = pd.read_csv(large_csv)
    full_sum = float(full_df["amount"].sum())  # pandas skips NaN, like the agent
    sample_sum = float(full_df.head(_SAMPLE_ROWS)["amount"].sum())

    # The two aggregates must be materially different, otherwise the test
    # cannot distinguish full-dataset processing from sampling.
    rel_gap = abs(full_sum - sample_sum) / abs(full_sum)
    assert rel_gap > 0.10, (
        f"Full ({full_sum:,.2f}) and sample ({sample_sum:,.2f}) aggregates are "
        f"too close (rel_gap={rel_gap:.4f}) to prove full-dataset processing."
    )

    # --- Upload the large file (profiling happens here) ---
    upload_start = time.monotonic()
    with open(large_csv, "rb") as fh:
        r = api_client.post(
            "/datasets", files={"file": ("large_sample.csv", fh, "text/csv")}
        )
    upload_profile_s = time.monotonic() - upload_start
    assert r.status_code == 200, r.text
    upload = r.json()["data"]
    assert upload["status"] == "parsed", upload
    assert upload["row_count"] == _ROWS, upload
    session_id = upload["session_id"]

    # --- Ask the aggregation question (the timed, budgeted path) ---
    started = api_client.post(
        f"/sessions/{session_id}/messages", json={"content": _QUESTION}
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["data"]["run_id"]

    final, run_seconds = _poll_run(api_client, run_id)

    assert final["status"] == "completed", (
        f"Run did not complete (status={final['status']}): "
        f"{final.get('stuck_explanation') or final}"
    )

    # --- (a) Latency budget: the answered question must land under 30s ---
    assert run_seconds < _RUN_BUDGET_S, (
        f"Aggregation run took {run_seconds:.2f}s, exceeding the "
        f"{_RUN_BUDGET_S:.0f}s budget (upload+profile was {upload_profile_s:.2f}s)."
    )

    # --- (b) Correctness: the answer reflects the FULL dataset, not a sample ---
    candidates = _collect_numeric_candidates(final)
    assert candidates, f"Agent surfaced no numeric result to verify: {final}"

    def _within(value: float, target: float, tol: float) -> bool:
        if target == 0:
            return abs(value) <= tol
        return abs(value - target) / abs(target) <= tol

    matches_full = any(_within(c, full_sum, 0.02) for c in candidates)
    matches_sample = any(_within(c, sample_sum, 0.02) for c in candidates)

    assert matches_full, (
        f"No agent number matched the full-dataset total {full_sum:,.2f} "
        f"(within 2%). Candidates: {candidates[:20]}"
    )
    assert not matches_sample, (
        f"An agent number matched the 1,000-row-sample total {sample_sum:,.2f} "
        f"— pipeline appears to be sampling, not processing the full file. "
        f"Candidates: {candidates[:20]}"
    )

    print(
        f"\n[large-file] rows={_ROWS:,} upload+profile={upload_profile_s:.2f}s "
        f"run={run_seconds:.2f}s full_sum={full_sum:,.2f} sample_sum={sample_sum:,.2f}"
    )
