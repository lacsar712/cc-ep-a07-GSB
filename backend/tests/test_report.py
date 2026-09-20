import csv
import hashlib
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cqrs import attach_artifact, complete_run, list_events, record_metric, start_run
from app.database import Base, get_db
from app.main import app
from app.report import build_run_report_csv, build_run_report_txt


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(_type, compiler, **kw):
        return "JSON"

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def completed_run(db):
    run = start_run(
        db,
        actor="researcher",
        project="p1",
        name="n1",
        dataset_content_sha256=sha("ds"),
        code_commit_sha="abc1234",
        description="d",
    )
    run = record_metric(
        db, run_id=run.id, actor="researcher", name="acc", value=0.9, step=1,
        expected_version=run.version,
    )
    run = attach_artifact(
        db, run_id=run.id, actor="researcher", name="model.bin",
        uri="file:///tmp/model.bin", content_sha256=sha("model"),
        media_type="application/octet-stream", expected_version=run.version,
    )
    return complete_run(
        db, run_id=run.id, actor="researcher", result_summary="done",
        expected_version=run.version,
    )


@pytest.fixture()
def client(db):
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _token(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def test_csv_report_fields_and_counts(db, completed_run):
    events = list_events(db, completed_run.id)
    text = build_run_report_csv(completed_run, events)
    rows = [r for r in csv.reader(io.StringIO(text.removeprefix("\ufeff"))) if r]

    run_fields = {r[1]: r[2] for r in rows if r[0] == "run"}
    assert run_fields["status"] == "completed"
    assert run_fields["dataset_content_sha256"] == sha("ds")
    assert run_fields["code_commit_sha"] == "abc1234"
    assert run_fields["result_summary"] == "done"
    assert int(run_fields["event_count"]) == len(events)

    event_rows = [r for r in rows if r[0] == "event"]
    assert len(event_rows) == len(events)  # 与事件时间线条数一致
    assert [int(r[1]) for r in event_rows] == [e.version for e in events]
    assert [r[2] for r in event_rows] == [e.event_type for e in events]

    metric_rows = [r for r in rows if r[0] == "metric"]
    assert len(metric_rows) == len(completed_run.metrics_json)
    assert metric_rows[0][1:4] == ["acc", "0.9", "1"]

    artifact_rows = [r for r in rows if r[0] == "artifact"]
    assert len(artifact_rows) == len(completed_run.artifacts_json)
    assert artifact_rows[0][1] == "model.bin"
    assert artifact_rows[0][3] == sha("model")


def test_txt_report_fields_and_counts(db, completed_run):
    events = list_events(db, completed_run.id)
    text = build_run_report_txt(completed_run, events)
    assert "status: completed" in text
    assert f"dataset_content_sha256: {sha('ds')}" in text
    assert "code_commit_sha: abc1234" in text
    assert "result_summary: done" in text
    assert f"事件摘要（共 {len(events)} 条）" in text
    assert f"指标（共 {len(completed_run.metrics_json)} 条）" in text
    assert f"产物（共 {len(completed_run.artifacts_json)} 条）" in text
    assert "acc = 0.9 @ step 1" in text
    assert "model.bin" in text
    assert sha("model") in text


def test_export_csv_as_researcher(client, completed_run):
    token = _token(client, "researcher", "lab123456")
    res = client.get(
        f"/api/runs/{completed_run.id}/export?format=csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    dispo = res.headers["content-disposition"]
    assert "attachment" in dispo and ".csv" in dispo
    body = res.content.decode("utf-8-sig")
    assert "completed" in body
    assert sha("ds") in body
    assert body.count("RunStarted") == 1


def test_export_txt_as_auditor(client, completed_run):
    token = _token(client, "auditor", "audit123456")
    res = client.get(
        f"/api/runs/{completed_run.id}/export?format=txt",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "attachment" in res.headers["content-disposition"]
    assert "事件摘要（共 4 条）" in res.text
    assert "status: completed" in res.text


def test_export_auditor_cannot_mutate(client, completed_run):
    token = _token(client, "auditor", "audit123456")
    res = client.post(
        f"/api/runs/{completed_run.id}/complete",
        json={"result_summary": "x", "expected_version": completed_run.version},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_export_requires_auth(client, completed_run):
    res = client.get(f"/api/runs/{completed_run.id}/export")
    assert res.status_code == 401


def test_export_unknown_run_404(client):
    token = _token(client, "researcher", "lab123456")
    res = client.get(
        f"/api/runs/{uuid4()}/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def test_export_invalid_format_422(client, completed_run):
    token = _token(client, "researcher", "lab123456")
    res = client.get(
        f"/api/runs/{completed_run.id}/export?format=pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
