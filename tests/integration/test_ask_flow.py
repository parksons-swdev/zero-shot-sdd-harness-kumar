"""End-to-end integration test for the ask-a-question flow (spec/api.md,
spec/agent.md). Exercises the full real stack: FastAPI app, real SQLite DB,
and the real Gemini API — no mocks. Requires AGENT_GEMINI_API_KEY (or
AGENT_ANTHROPIC_API_KEY) in .env; skipped otherwise (see `_require_llm_key`
in tests/conftest.py).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

FIXTURE_CSV = Path(__file__).parent.parent / "fixtures" / "sample_sales.csv"
_POLL_TIMEOUT_S = 90
_POLL_INTERVAL_S = 1.5


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path, monkeypatch):
    """Keep uploaded CSVs inside pytest's tmp_path instead of the repo's
    real ./data/uploads directory."""
    monkeypatch.setenv("AGENT_UPLOAD_DIR", str(tmp_path / "uploads"))
    yield


def _upload_sample(api_client):
    with open(FIXTURE_CSV, "rb") as fh:
        r = api_client.post("/datasets", files={"file": ("sample_sales.csv", fh, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _poll_run(api_client, run_id: str) -> dict:
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    last = None
    while time.monotonic() < deadline:
        r = api_client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        last = r.json()["data"]
        if last["status"] not in ("pending", "running"):
            return last
        time.sleep(_POLL_INTERVAL_S)
    raise AssertionError(
        f"Run {run_id} did not reach a terminal status within {_POLL_TIMEOUT_S}s: {last}"
    )


def test_ask_flow_happy_path_real_gemini(api_client, _require_llm_key):
    """Upload a real CSV, ask a real question through the real Gemini API,
    poll to completion, and verify the full audit trail + history views."""
    upload = _upload_sample(api_client)
    assert upload["status"] == "parsed"
    session_id = upload["session_id"]

    started = api_client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "what is the total revenue by region?"},
    )
    assert started.status_code == 200
    started_data = started.json()["data"]
    assert started_data["status"] == "running"
    run_id = started_data["run_id"]

    final = _poll_run(api_client, run_id)

    assert final["status"] == "completed", final
    assert final["answer_text"]
    assert isinstance(final["chart_spec"], dict)
    assert final["chart_spec"]["type"] != "none"
    assert isinstance(final["table_data"], list)
    assert len(final["table_data"]) > 0
    assert final["generated_code"]
    assert final["token_input_count"] > 0
    assert final["token_output_count"] > 0

    # History: GET /runs lists it, GET /sessions/{id}/messages has both turns.
    history = api_client.get("/runs?limit=10&offset=0").json()["data"]
    assert any(r["run_id"] == run_id for r in history)

    detail = api_client.get(f"/runs/{run_id}").json()["data"]
    assert detail["question_text"] == "what is the total revenue by region?"

    messages = api_client.get(f"/sessions/{session_id}/messages").json()["data"]
    roles = [m["role"] for m in messages]
    assert roles.count("user") == 1
    assert "assistant" in roles
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert assistant_msg["run_id"] == run_id


def test_ask_flow_rejects_concurrent_run_for_same_session(api_client, _require_llm_key):
    """Concurrency guard (spec/agent.md): a second question on the same
    session while the first is still running must be rejected 409."""
    upload = _upload_sample(api_client)
    session_id = upload["session_id"]

    first = api_client.post(
        f"/sessions/{session_id}/messages", json={"content": "what is the total revenue?"}
    )
    assert first.status_code == 200
    run_id = first.json()["data"]["run_id"]

    second = api_client.post(
        f"/sessions/{session_id}/messages", json={"content": "and by product?"}
    )
    assert second.status_code == 409

    # Drain the first run so no background thread outlives the test/DB.
    _poll_run(api_client, run_id)


def test_ask_flow_edge_case_session_without_dataset_rejected(api_client):
    """Edge case: a session with no attached dataset cannot start a run
    (no LLM call is ever made — rejected before the graph is invoked)."""
    from db.models import Session as SessionModel
    from db.session import create_db_session

    with create_db_session() as db:
        sess = SessionModel(dataset_id=None)
        db.add(sess)
        db.flush()
        session_id = sess.id

    r = api_client.post(f"/sessions/{session_id}/messages", json={"content": "anything"})
    assert r.status_code == 400
