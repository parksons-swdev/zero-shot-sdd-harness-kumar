"""Integration tests for the Phase 2 history-api slice (spec/api.md):

- GET /runs with q / date_from / date_to filters + pagination
- GET /datasets listing (parsed only, newest-first)
- POST /sessions reselect flow (create against an existing parsed dataset)

These are DB-level tests: they seed rows directly and exercise the real
FastAPI app + real SQLite driver (via the shared isolated-DB fixture in
tests/conftest.py). No LLM/Gemini call is involved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.models import Dataset, Run
from db.models import Session as SessionModel
from db.session import create_db_session


def _mk_dataset(db, *, filename="data.csv", status="parsed", row_count=100, created_at=None):
    ds = Dataset(
        filename=filename,
        file_path=f"/tmp/{filename}",
        size_bytes=1234,
        row_count=row_count,
        column_count=5,
        status=status,
    )
    if created_at is not None:
        ds.created_at = created_at
    db.add(ds)
    db.flush()
    return ds.id


def _mk_run(db, *, dataset_id, session_id, question, created_at, status="completed", cost=0.01):
    run = Run(
        session_id=session_id,
        dataset_id=dataset_id,
        question_text=question,
        status=status,
        estimated_cost_usd=cost,
    )
    run.created_at = created_at
    db.add(run)
    db.flush()
    return run.id


@pytest.fixture
def seeded(_isolated_db):
    """Seed a dataset, a session, and three runs at known timestamps."""
    base = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ids = {}
    with create_db_session() as db:
        ds_id = _mk_dataset(db, filename="sales.csv")
        sess = SessionModel(dataset_id=ds_id)
        db.add(sess)
        db.flush()
        sess_id = sess.id

        ids["revenue"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id,
            question="What is total revenue by region?", created_at=base,
        )
        ids["orders"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id,
            question="How many orders last month?", created_at=base + timedelta(days=10),
        )
        ids["revenue2"] = _mk_run(
            db, dataset_id=ds_id, session_id=sess_id,
            question="Revenue trend over time?", created_at=base + timedelta(days=20),
        )
        ids["dataset_id"] = ds_id
        ids["session_id"] = sess_id
        ids["base"] = base
    return ids


# --- GET /runs search -------------------------------------------------------

def test_search_narrows_by_keyword(api_client, seeded):
    r = api_client.get("/runs", params={"q": "revenue"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    returned = {row["run_id"] for row in data}
    assert returned == {seeded["revenue"], seeded["revenue2"]}


def test_search_is_case_insensitive(api_client, seeded):
    r = api_client.get("/runs", params={"q": "REVENUE"})
    assert r.status_code == 200
    returned = {row["run_id"] for row in r.json()["data"]}
    assert returned == {seeded["revenue"], seeded["revenue2"]}


def test_search_no_match_returns_empty(api_client, seeded):
    r = api_client.get("/runs", params={"q": "nonexistent-term"})
    assert r.status_code == 200
    assert r.json()["data"] == []


# --- GET /runs date range ---------------------------------------------------

def test_date_range_filters_correctly(api_client, seeded):
    base = seeded["base"]
    # Window that includes only the middle ("orders") run.
    r = api_client.get(
        "/runs",
        params={
            "date_from": (base + timedelta(days=5)).isoformat(),
            "date_to": (base + timedelta(days=15)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    returned = {row["run_id"] for row in r.json()["data"]}
    assert returned == {seeded["orders"]}


def test_date_from_accepts_plain_date(api_client, seeded):
    # A plain ISO date (no time) should be accepted and treated as UTC midnight.
    base = seeded["base"]
    r = api_client.get("/runs", params={"date_from": (base + timedelta(days=15)).date().isoformat()})
    assert r.status_code == 200
    returned = {row["run_id"] for row in r.json()["data"]}
    assert returned == {seeded["revenue2"]}


def test_invalid_date_returns_400(api_client, seeded):
    r = api_client.get("/runs", params={"date_from": "not-a-date"})
    assert r.status_code == 400


def test_filters_compose_as_and(api_client, seeded):
    base = seeded["base"]
    r = api_client.get(
        "/runs",
        params={
            "q": "revenue",
            "date_from": (base + timedelta(days=15)).isoformat(),
        },
    )
    assert r.status_code == 200
    returned = {row["run_id"] for row in r.json()["data"]}
    # Only "revenue2" is both a revenue question AND after day 15.
    assert returned == {seeded["revenue2"]}


# --- GET /runs pagination + envelope ---------------------------------------

def test_pagination_works(api_client, seeded):
    first = api_client.get("/runs", params={"limit": 2, "offset": 0}).json()["data"]
    second = api_client.get("/runs", params={"limit": 2, "offset": 2}).json()["data"]
    assert len(first) == 2
    assert len(second) == 1
    # Newest first: revenue2 (day 20) then orders (day 10) then revenue (day 0).
    assert first[0]["run_id"] == seeded["revenue2"]
    assert second[0]["run_id"] == seeded["revenue"]


def test_runs_envelope_shape(api_client, seeded):
    body = api_client.get("/runs").json()
    assert body["error"] is None
    row = body["data"][0]
    assert set(row.keys()) == {
        "run_id", "dataset_filename", "question_text",
        "status", "estimated_cost_usd", "created_at",
    }
    assert row["dataset_filename"] == "sales.csv"


# --- GET /datasets ----------------------------------------------------------

def test_datasets_lists_only_parsed_newest_first(api_client, _isolated_db):
    base = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
    with create_db_session() as db:
        older = _mk_dataset(db, filename="older.csv", status="parsed", created_at=base)
        newer = _mk_dataset(
            db, filename="newer.csv", status="parsed", created_at=base + timedelta(days=1)
        )
        _mk_dataset(db, filename="pending.csv", status="uploaded", created_at=base + timedelta(days=2))
        _mk_dataset(db, filename="bad.csv", status="needs_decision", created_at=base + timedelta(days=3))

    r = api_client.get("/datasets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    data = body["data"]
    filenames = [d["filename"] for d in data]
    assert filenames == ["newer.csv", "older.csv"]
    assert set(data[0].keys()) == {"dataset_id", "filename", "row_count", "created_at"}
    assert data[0]["dataset_id"] == newer
    assert data[1]["dataset_id"] == older


def test_datasets_empty(api_client, _isolated_db):
    r = api_client.get("/datasets")
    assert r.status_code == 200
    assert r.json() == {"data": [], "error": None}


# --- POST /sessions ---------------------------------------------------------

def test_create_session_binds_to_existing_dataset(api_client, _isolated_db):
    with create_db_session() as db:
        ds_id = _mk_dataset(db, filename="reselect.csv", status="parsed")

    r = api_client.post("/sessions", json={"dataset_id": ds_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["data"]["dataset_id"] == ds_id
    session_id = body["data"]["session_id"]
    assert session_id

    # The session really exists and is bound to the dataset.
    with create_db_session() as db:
        sess = db.get(SessionModel, session_id)
        assert sess is not None
        assert sess.dataset_id == ds_id


def test_create_session_404_on_unknown_dataset(api_client, _isolated_db):
    r = api_client.post("/sessions", json={"dataset_id": "does-not-exist"})
    assert r.status_code == 404


def test_create_session_404_on_unparsed_dataset(api_client, _isolated_db):
    with create_db_session() as db:
        ds_id = _mk_dataset(db, filename="unparsed.csv", status="needs_decision")

    r = api_client.post("/sessions", json={"dataset_id": ds_id})
    assert r.status_code == 404
