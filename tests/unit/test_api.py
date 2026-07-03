"""API contract tests for the CSV Insight Agent's dataset/session/run
endpoints (spec/api.md). No LLM key required — the graph is never invoked
here (that's covered by tests/integration/test_ask_flow.py); these tests
exercise upload/profile/decision/history routes against a real SQLite DB.
"""
from __future__ import annotations

import io

import pytest


GOOD_CSV = b"region,revenue\nNorth,100\nSouth,200\nEast,300\n"
RAGGED_CSV = b"a,b,c\n1,2,3\n4,5,6,7\n8,9,10\n"


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path, monkeypatch):
    """Keep uploaded CSVs inside pytest's tmp_path instead of the repo's
    real ./data/uploads directory."""
    monkeypatch.setenv("AGENT_UPLOAD_DIR", str(tmp_path / "uploads"))
    yield


def _upload(api_client, content: bytes = GOOD_CSV, filename: str = "sales.csv"):
    return api_client.post(
        "/datasets", files={"file": (filename, io.BytesIO(content), "text/csv")}
    )


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /datasets
# ---------------------------------------------------------------------------


def test_upload_dataset_happy_path(api_client):
    r = _upload(api_client)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "parsed"
    assert data["row_count"] == 3
    assert data["column_count"] == 2
    assert data["filename"] == "sales.csv"
    assert "dataset_id" in data and "session_id" in data
    assert {c["name"] for c in data["schema"]} == {"region", "revenue"}


def test_upload_dataset_rejects_non_csv(api_client):
    r = api_client.post(
        "/datasets", files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    )
    assert r.status_code == 400


def test_upload_dataset_needs_decision_on_ragged_rows(api_client):
    r = _upload(api_client, content=RAGGED_CSV, filename="ragged.csv")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "needs_decision"
    assert "skip_bad_lines" in data["choices"]


# ---------------------------------------------------------------------------
# POST /datasets/{id}/decisions
# ---------------------------------------------------------------------------


def test_resolve_decision_skip_bad_lines(api_client):
    upload = _upload(api_client, content=RAGGED_CSV, filename="ragged.csv").json()["data"]
    dataset_id = upload["dataset_id"]

    r = api_client.post(f"/datasets/{dataset_id}/decisions", json={"choice": "skip_bad_lines"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "parsed"
    assert data["row_count"] == 2


def test_resolve_decision_unknown_choice_rejected(api_client):
    upload = _upload(api_client, content=RAGGED_CSV, filename="ragged.csv").json()["data"]
    dataset_id = upload["dataset_id"]

    r = api_client.post(f"/datasets/{dataset_id}/decisions", json={"choice": "not_a_real_choice"})
    assert r.status_code == 400


def test_resolve_decision_unknown_dataset_404(api_client):
    r = api_client.post("/datasets/nonexistent-id/decisions", json={"choice": "skip_bad_lines"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /datasets/{id}
# ---------------------------------------------------------------------------


def test_get_dataset_not_found(api_client):
    r = api_client.get("/datasets/nonexistent-id")
    assert r.status_code == 404


def test_get_dataset_returns_profile(api_client):
    upload = _upload(api_client).json()["data"]
    r = api_client.get(f"/datasets/{upload['dataset_id']}")
    assert r.status_code == 200
    assert r.json()["data"]["row_count"] == 3


# ---------------------------------------------------------------------------
# POST/GET /sessions/{id}/messages
# ---------------------------------------------------------------------------


def test_post_message_unknown_session_404(api_client):
    r = api_client.post("/sessions/nonexistent-id/messages", json={"content": "hi"})
    assert r.status_code == 404


def test_post_message_empty_content_rejected(api_client):
    upload = _upload(api_client).json()["data"]
    r = api_client.post(f"/sessions/{upload['session_id']}/messages", json={"content": "   "})
    assert r.status_code == 400


def test_post_message_no_dataset_rejected(api_client):
    from db.models import Session as SessionModel
    from db.session import create_db_session

    with create_db_session() as db:
        sess = SessionModel(dataset_id=None)
        db.add(sess)
        db.flush()
        session_id = sess.id

    r = api_client.post(f"/sessions/{session_id}/messages", json={"content": "hello"})
    assert r.status_code == 400


def test_post_message_rejects_second_run_while_one_in_progress(api_client, monkeypatch):
    # Stub out the actual graph execution so we can deterministically leave a
    # run "in progress" without needing a real LLM call in this unit test.
    monkeypatch.setattr("api.sessions.start_run", lambda *a, **k: None)

    upload = _upload(api_client).json()["data"]
    session_id = upload["session_id"]

    r1 = api_client.post(f"/sessions/{session_id}/messages", json={"content": "q1"})
    assert r1.status_code == 200
    assert r1.json()["data"]["status"] == "running"

    r2 = api_client.post(f"/sessions/{session_id}/messages", json={"content": "q2"})
    assert r2.status_code == 409


def test_get_messages_unknown_session_404(api_client):
    r = api_client.get("/sessions/nonexistent-id/messages")
    assert r.status_code == 404


def test_get_messages_lists_history(api_client, monkeypatch):
    monkeypatch.setattr("api.sessions.start_run", lambda *a, **k: None)
    upload = _upload(api_client).json()["data"]
    session_id = upload["session_id"]

    api_client.post(f"/sessions/{session_id}/messages", json={"content": "what is the total?"})

    r = api_client.get(f"/sessions/{session_id}/messages")
    assert r.status_code == 200
    messages = r.json()["data"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "what is the total?"


# ---------------------------------------------------------------------------
# GET /runs/{id}, GET /runs
# ---------------------------------------------------------------------------


def test_get_run_not_found(api_client):
    r = api_client.get("/runs/nonexistent-id")
    assert r.status_code == 404


def test_get_run_running_shape(api_client, monkeypatch):
    monkeypatch.setattr("api.sessions.start_run", lambda *a, **k: None)
    upload = _upload(api_client).json()["data"]
    session_id = upload["session_id"]

    started = api_client.post(f"/sessions/{session_id}/messages", json={"content": "q1"}).json()[
        "data"
    ]
    run_id = started["run_id"]

    r = api_client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "running"
    assert "step_count" in data and "total_estimated_steps" in data


def test_list_runs_history(api_client, monkeypatch):
    monkeypatch.setattr("api.sessions.start_run", lambda *a, **k: None)
    upload = _upload(api_client).json()["data"]
    session_id = upload["session_id"]
    api_client.post(f"/sessions/{session_id}/messages", json={"content": "q1"})

    r = api_client.get("/runs?limit=10&offset=0")
    assert r.status_code == 200
    runs = r.json()["data"]
    assert len(runs) == 1
    assert runs[0]["question_text"] == "q1"
    assert runs[0]["dataset_filename"] == "sales.csv"
