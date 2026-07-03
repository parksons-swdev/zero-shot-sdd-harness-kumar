"""Integration tests for GET /usage — the sidebar token/cost utilization
widget (running totals + a recent-runs breakdown).

DB-level tests: seed rows directly and exercise the real FastAPI app + real
SQLite driver (via the shared isolated-DB fixture in tests/conftest.py). No
LLM/Gemini call is involved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.models import Dataset, Run
from db.models import Session as SessionModel
from db.session import create_db_session


def _mk_dataset(db, *, filename="data.csv"):
    ds = Dataset(
        filename=filename,
        file_path=f"/tmp/{filename}",
        size_bytes=1234,
        row_count=100,
        column_count=5,
        status="parsed",
    )
    db.add(ds)
    db.flush()
    return ds.id


def _mk_run(
    db,
    *,
    dataset_id,
    session_id,
    question,
    created_at,
    status="completed",
    token_input_count=0,
    token_output_count=0,
    cost=0.0,
):
    run = Run(
        session_id=session_id,
        dataset_id=dataset_id,
        question_text=question,
        status=status,
        token_input_count=token_input_count,
        token_output_count=token_output_count,
        estimated_cost_usd=cost,
    )
    run.created_at = created_at
    db.add(run)
    db.flush()
    return run.id


@pytest.fixture
def seeded(_isolated_db):
    """Seed a dataset/session and three completed runs with known usage, plus
    one still-`running` run that must be excluded from the breakdown (but
    still counted in totals, per the spec: token_usage is a running total)."""
    base = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ids = {}
    with create_db_session() as db:
        ds_id = _mk_dataset(db)
        sess = SessionModel(dataset_id=ds_id)
        db.add(sess)
        db.flush()
        sess_id = sess.id

        ids["a"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id, question="Q1",
            created_at=base, token_input_count=100, token_output_count=50, cost=0.001,
        )
        ids["b"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id, question="Q2",
            created_at=base + timedelta(minutes=5), token_input_count=200,
            token_output_count=80, cost=0.002,
        )
        ids["c_failed"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id, question="Q3 (failed)",
            created_at=base + timedelta(minutes=10), status="failed",
            token_input_count=50, token_output_count=10, cost=0.0005,
        )
        ids["running"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id, question="Q4 (still running)",
            created_at=base + timedelta(minutes=15), status="running",
        )
        ids["dataset_id"] = ds_id
        ids["session_id"] = sess_id
    return ids


def test_usage_totals_sum_across_all_runs(api_client, seeded):
    r = api_client.get("/usage")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total_input_tokens"] == 100 + 200 + 50
    assert data["total_output_tokens"] == 50 + 80 + 10
    assert round(data["total_cost_usd"], 6) == round(0.001 + 0.002 + 0.0005, 6)
    assert data["run_count"] == 4  # includes the still-running row


def test_usage_breakdown_excludes_running_runs(api_client, seeded):
    r = api_client.get("/usage")
    data = r.json()["data"]
    returned_ids = {row["run_id"] for row in data["runs"]}
    assert seeded["running"] not in returned_ids
    assert {seeded["a"], seeded["b"], seeded["c_failed"]} == returned_ids


def test_usage_breakdown_is_newest_first(api_client, seeded):
    r = api_client.get("/usage")
    rows = r.json()["data"]["runs"]
    assert [row["run_id"] for row in rows] == [seeded["c_failed"], seeded["b"], seeded["a"]]


def test_usage_breakdown_row_shape(api_client, seeded):
    r = api_client.get("/usage")
    row = next(row for row in r.json()["data"]["runs"] if row["run_id"] == seeded["a"])
    assert row["question_text"] == "Q1"
    assert row["token_input_count"] == 100
    assert row["token_output_count"] == 50
    assert round(row["estimated_cost_usd"], 6) == 0.001
    assert row["created_at"]


def test_usage_with_no_runs_returns_zeros(api_client, _isolated_db):
    r = api_client.get("/usage")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data == {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "run_count": 0,
        "runs": [],
    }
