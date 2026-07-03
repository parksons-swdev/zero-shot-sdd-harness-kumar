"""DB layer tests — no LLM key required."""
from sqlalchemy.orm import Session as OrmSession
from db.models import RunRow, Dataset, Session as SessionRow, Message, Run, RunStep
import db.session as session_module


def test_run_row_roundtrip(_isolated_db):
    with OrmSession(_isolated_db) as s:
        run = RunRow(input_text="hello world")
        s.add(run)
        s.commit()
        run_id = run.id

    with OrmSession(_isolated_db) as s:
        fetched = s.get(RunRow, run_id)
        assert fetched is not None
        assert fetched.input_text == "hello world"
        assert fetched.status == "pending"
        assert fetched.output_text is None


def test_run_row_status_update(_isolated_db):
    with OrmSession(_isolated_db) as s:
        run = RunRow(input_text="test")
        s.add(run)
        s.commit()
        run_id = run.id

    with OrmSession(_isolated_db) as s:
        run = s.get(RunRow, run_id)
        run.status = "completed"
        run.output_text = "some output"
        s.commit()

    with OrmSession(_isolated_db) as s:
        run = s.get(RunRow, run_id)
        assert run.status == "completed"
        assert run.output_text == "some output"


def test_multiple_runs_independent(_isolated_db):
    ids = []
    with OrmSession(_isolated_db) as s:
        for i in range(3):
            run = RunRow(input_text=f"input {i}")
            s.add(run)
        s.commit()
        # fetch all
        runs = s.query(RunRow).all()
        ids = [r.id for r in runs]

    assert len(ids) == 3
    assert len(set(ids)) == 3  # all unique


# --- CSV Insight Agent entities (spec/data.md) -----------------------------


def test_dataset_roundtrip(_isolated_db):
    with OrmSession(_isolated_db) as s:
        ds = Dataset(
            filename="sales.csv",
            file_path="./data/uploads/x.csv",
            size_bytes=1024,
            row_count=100,
            column_count=5,
            schema_json={"revenue": {"dtype": "float64", "null_pct": 0.0}},
            anomalies_json=[{"column": "revenue", "type": "outliers", "severity": "low", "description": "3 outliers"}],
            status="parsed",
        )
        s.add(ds)
        s.commit()
        ds_id = ds.id

    with OrmSession(_isolated_db) as s:
        fetched = s.get(Dataset, ds_id)
        assert fetched is not None
        assert fetched.filename == "sales.csv"
        assert fetched.row_count == 100
        assert fetched.schema_json["revenue"]["dtype"] == "float64"
        assert fetched.anomalies_json[0]["type"] == "outliers"
        assert fetched.status == "parsed"


def test_dataset_defaults_and_minimal_required_fields(_isolated_db):
    """Edge case: only the required fields are set at upload time (before parsing)."""
    with OrmSession(_isolated_db) as s:
        ds = Dataset(filename="raw.csv", file_path="./data/uploads/raw.csv", size_bytes=10, status="uploaded")
        s.add(ds)
        s.commit()
        ds_id = ds.id

    with OrmSession(_isolated_db) as s:
        fetched = s.get(Dataset, ds_id)
        assert fetched.row_count is None
        assert fetched.column_count is None
        assert fetched.schema_json is None
        assert fetched.anomalies_json is None
        assert fetched.status == "uploaded"


def test_session_nullable_dataset_and_fk_link(_isolated_db):
    """Session can exist before a dataset is attached; then link to a real dataset."""
    with OrmSession(_isolated_db) as s:
        sess = SessionRow()
        s.add(sess)
        s.commit()
        sess_id = sess.id

    with OrmSession(_isolated_db) as s:
        fetched = s.get(SessionRow, sess_id)
        assert fetched.dataset_id is None

    with OrmSession(_isolated_db) as s:
        ds = Dataset(filename="a.csv", file_path="./a.csv", size_bytes=1, status="parsed")
        s.add(ds)
        s.commit()
        sess = s.get(SessionRow, sess_id)
        sess.dataset_id = ds.id
        s.commit()

    with OrmSession(_isolated_db) as s:
        fetched = s.get(SessionRow, sess_id)
        assert fetched.dataset_id is not None


def test_message_roundtrip_and_role_variants(_isolated_db):
    with OrmSession(_isolated_db) as s:
        sess = SessionRow()
        s.add(sess)
        s.commit()
        sess_id = sess.id

    with OrmSession(_isolated_db) as s:
        m1 = Message(session_id=sess_id, role="user", content="What is total revenue?")
        m2 = Message(session_id=sess_id, role="assistant", content="Total revenue is 120,000.")
        s.add_all([m1, m2])
        s.commit()

    with OrmSession(_isolated_db) as s:
        msgs = s.query(Message).filter(Message.session_id == sess_id).order_by(Message.created_at).all()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"
        assert msgs[1].run_id is None


def test_run_full_lifecycle_roundtrip(_isolated_db):
    """Happy path: a completed Run with full audit-trail fields populated."""
    with OrmSession(_isolated_db) as s:
        ds = Dataset(filename="a.csv", file_path="./a.csv", size_bytes=1, status="parsed")
        sess = SessionRow()
        s.add_all([ds, sess])
        s.commit()
        ds_id, sess_id = ds.id, sess.id

    with OrmSession(_isolated_db) as s:
        run = Run(
            session_id=sess_id,
            dataset_id=ds_id,
            question_text="What is total revenue by region?",
            status="completed",
            generated_code="def analyze(df):\n    return df.groupby('region')['revenue'].sum()",
            answer_text="North leads with 120,000.",
            key_numbers_json={"total_revenue": 120000},
            chart_spec_json={"type": "bar", "series": [{"x": "North", "y": 120000}]},
            table_data_json=[{"region": "North", "revenue": 120000}],
            token_input_count=500,
            token_output_count=200,
            estimated_cost_usd=0.0123,
        )
        s.add(run)
        s.commit()
        run_id = run.id

    with OrmSession(_isolated_db) as s:
        fetched = s.get(Run, run_id)
        assert fetched.status == "completed"
        assert fetched.retry_count == 0
        assert fetched.step_count == 0
        assert fetched.chart_spec_json["type"] == "bar"
        assert float(fetched.estimated_cost_usd) == 0.0123
        assert fetched.completed_at is None  # not set in this test — set by graph on terminal state


def test_run_needs_clarification_edge_case(_isolated_db):
    """Edge case: a run that stops for clarification has no generated_code/answer yet."""
    with OrmSession(_isolated_db) as s:
        ds = Dataset(filename="a.csv", file_path="./a.csv", size_bytes=1, status="parsed")
        sess = SessionRow()
        s.add_all([ds, sess])
        s.commit()
        ds_id, sess_id = ds.id, sess.id

    with OrmSession(_isolated_db) as s:
        run = Run(
            session_id=sess_id,
            dataset_id=ds_id,
            question_text="show me the best one",
            status="needs_clarification",
            clarification_question="Which metric defines 'best' — revenue or units sold?",
        )
        s.add(run)
        s.commit()
        run_id = run.id

    with OrmSession(_isolated_db) as s:
        fetched = s.get(Run, run_id)
        assert fetched.status == "needs_clarification"
        assert fetched.clarification_question is not None
        assert fetched.generated_code is None
        assert fetched.answer_text is None


def test_run_failed_error_path_requires_dataset_and_session_fk(_isolated_db):
    """Error path: Run.session_id/dataset_id are non-nullable — violating that fails."""
    from sqlalchemy.exc import IntegrityError

    with OrmSession(_isolated_db) as s:
        run = Run(session_id=None, dataset_id=None, question_text="broken")
        s.add(run)
        try:
            s.commit()
            raised = False
        except IntegrityError:
            s.rollback()
            raised = True
    assert raised, "Run without session_id/dataset_id should violate NOT NULL constraint"


def test_run_step_audit_trail_multi_step_and_error_flag(_isolated_db):
    """Multi-interaction: a run accumulates several ordered RunStep rows, including an error step."""
    with OrmSession(_isolated_db) as s:
        ds = Dataset(filename="a.csv", file_path="./a.csv", size_bytes=1, status="parsed")
        sess = SessionRow()
        s.add_all([ds, sess])
        s.commit()
        run = Run(session_id=sess.id, dataset_id=ds.id, question_text="q", status="completed")
        s.add(run)
        s.commit()
        run_id = run.id

    with OrmSession(_isolated_db) as s:
        steps = [
            RunStep(run_id=run_id, step_number=1, step_type="load_context", label="Loading dataset context"),
            RunStep(run_id=run_id, step_number=2, step_type="classify_request", label="Classifying request"),
            RunStep(
                run_id=run_id,
                step_number=3,
                step_type="execute_code",
                label="Executing analysis code (attempt 1)",
                code_snippet="df.groupby('region').sum()",
                is_error=True,
                output_summary="KeyError: 'region'",
            ),
            RunStep(run_id=run_id, step_number=4, step_type="generate_code", label="Writing analysis code (attempt 2)"),
        ]
        s.add_all(steps)
        s.commit()

    with OrmSession(_isolated_db) as s:
        fetched = (
            s.query(RunStep)
            .filter(RunStep.run_id == run_id)
            .order_by(RunStep.step_number)
            .all()
        )
        assert len(fetched) == 4
        assert [st.step_number for st in fetched] == [1, 2, 3, 4]
        assert fetched[2].is_error is True
        assert fetched[2].output_summary == "KeyError: 'region'"
        assert fetched[0].is_error is False
        assert fetched[-1].step_type == "generate_code"


def test_run_step_requires_run_id(_isolated_db):
    """Error path: RunStep.run_id is non-nullable."""
    from sqlalchemy.exc import IntegrityError

    with OrmSession(_isolated_db) as s:
        step = RunStep(run_id=None, step_number=1, step_type="load_context", label="x")
        s.add(step)
        try:
            s.commit()
            raised = False
        except IntegrityError:
            s.rollback()
            raised = True
    assert raised, "RunStep without run_id should violate NOT NULL constraint"
