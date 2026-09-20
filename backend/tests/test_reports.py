"""报告导出测试：渲染内容一致性 + API 鉴权（审计员只读）。"""

from __future__ import annotations

import csv
import hashlib
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB

from app.auth import create_access_token
from app.cqrs import (
    attach_artifact,
    complete_run,
    list_events,
    record_metric,
    start_run,
)
from app.database import Base, get_db
from app.main import app
from app.models import RunProjection
from app.reports import render_csv_report, render_text_report


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
        project="protein-folding",
        name="AlphaFold baseline v1",
        dataset_content_sha256=sha("casp14-subset-v1"),
        code_commit_sha="a1b2c3d4e5f6",
        description="基线折叠实验",
    )
    run = record_metric(
        db, run_id=run.id, actor="researcher", name="tm_score",
        value=0.81, step=2, expected_version=run.version,
    )
    run = attach_artifact(
        db, run_id=run.id, actor="researcher", name="structure.pdb",
        uri="s3://lab-artifacts/structure.pdb",
        content_sha256=sha("structure-pdb"),
        media_type="chemical/x-pdb", expected_version=run.version,
    )
    run = complete_run(
        db, run_id=run.id, actor="researcher",
        result_summary="基线完成，TM-score=0.81", expected_version=run.version,
    )
    return run


# ---------- 渲染层：字段与投影 / 事件流一致 ----------

def test_csv_report_contains_all_required_sections(db, completed_run):
    events = list_events(db, completed_run.id)
    text = render_csv_report(completed_run, events)
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    flat = {tuple(r[:2]): r for r in rows if r}

    meta = {r[1]: r[2] for r in rows if len(r) >= 3 and r[0] == "meta"}
    assert meta["status"] == "completed"
    assert meta["dataset_content_sha256"] == completed_run.dataset_content_sha256
    assert meta["code_commit_sha"] == completed_run.code_commit_sha
    assert meta["event_count"] == str(len(events))
    assert meta["metric_count"] == "1"
    assert meta["artifact_count"] == "1"

    event_rows = [r for r in rows if r and r[0] == "event"]
    assert len(event_rows) == len(events)
    assert [r[2] for r in event_rows] == [e.event_type for e in events]
    assert event_rows[-1][2] == "RunCompleted"

    metric_rows = [r for r in rows if r and r[0] == "metric"]
    assert metric_rows[0][2] == "tm_score"
    artifact_rows = [r for r in rows if r and r[0] == "artifact"]
    assert artifact_rows[0][1] == "structure.pdb"
    assert artifact_rows[0][3] == completed_run.artifacts_json[0]["content_sha256"]


def test_text_report_matches_projection_and_timeline(db, completed_run):
    events = list_events(db, completed_run.id)
    text = render_text_report(completed_run, events)

    assert "状态: completed（已完成）" in text
    assert completed_run.dataset_content_sha256 in text
    assert completed_run.code_commit_sha in text
    assert "基线完成，TM-score=0.81" in text

    # 时间线条数一致：每个事件一行 vN | EventType
    headers = [ln for ln in text.splitlines() if ln.startswith("v") and " | " in ln]
    assert len(headers) == len(events)
    for line, event in zip(headers, events):
        assert f"v{event.version}" in line
        assert event.event_type in line

    assert "tm_score" in text and "0.81" in text
    assert "structure.pdb" in text
    assert completed_run.artifacts_json[0]["content_sha256"] in text


def test_text_report_handles_running_run_without_finish(db):
    run = start_run(
        db, actor="researcher", project="p", name="n",
        dataset_content_sha256=sha("ds"), code_commit_sha="abc1234",
        description=None,
    )
    text = render_text_report(run, list_events(db, run.id))
    assert "running（进行中）" in text
    assert "[指标] 共 0 条" in text
    assert "[产物] 共 0 条" in text
    assert "（无）" in text


# ---------- API 层：鉴权与下载 ----------

@pytest.fixture()
def client(db):
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    # 不使用 with：跳过 app lifespan（它会对真实 Postgres 执行 create_all），
    # 本测试的内存 SQLite 表已由 db fixture 建好。
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(role, role)}"}


def test_report_requires_login(client, completed_run):
    r = client.get(f"/api/runs/{completed_run.id}/report")
    assert r.status_code == 401


def test_auditor_can_download_txt_and_csv_but_cannot_mutate(client, completed_run):
    run_id = completed_run.id

    r_txt = client.get(f"/api/runs/{run_id}/report?format=txt", headers=_auth("auditor"))
    assert r_txt.status_code == 200
    assert r_txt.headers["content-type"].startswith("text/plain")
    assert "attachment" in r_txt.headers["content-disposition"]
    assert r_txt.headers["x-event-count"] == "4"
    assert "dataset_content_sha256" in r_txt.text

    r_csv = client.get(f"/api/runs/{run_id}/report?format=csv", headers=_auth("auditor"))
    assert r_csv.status_code == 200
    assert r_csv.headers["content-type"].startswith("text/csv")
    assert r_csv.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM

    # 审计员只读：写命令必须被拒，报告下载不得成为改数据的入口
    r_forbidden = client.post(
        f"/api/runs/{run_id}/metrics",
        headers=_auth("auditor"),
        json={"name": "x", "value": 1.0, "step": 1, "expected_version": 4},
    )
    assert r_forbidden.status_code == 403


def test_researcher_report_matches_timeline_count(client, db, completed_run):
    run_id = completed_run.id
    r = client.get(f"/api/runs/{run_id}/report?format=txt", headers=_auth("researcher"))
    assert r.status_code == 200
    timeline = list_events(db, run_id)
    assert r.headers["x-event-count"] == str(len(timeline))


def test_report_unknown_run_and_bad_format(client, completed_run):
    r404 = client.get(f"/api/runs/{uuid4()}/report", headers=_auth("auditor"))
    assert r404.status_code == 404

    r422 = client.get(
        f"/api/runs/{completed_run.id}/report?format=pdf", headers=_auth("auditor")
    )
    assert r422.status_code == 422


def test_end_to_end_report_fields_match_detail_and_timeline(client):
    """验收核对：导出的已完成 Run，文件字段与详情、时间线条数一致。"""
    hdr = _auth("researcher")
    created = client.post(
        "/api/runs",
        headers=hdr,
        json={
            "project": "protein-folding",
            "name": "核对用 Run",
            "dataset_content_sha256": sha("dataset-x"),
            "code_commit_sha": "abcdef1234",
            "description": "端到端核对",
            "expected_version": 0,
        },
    ).json()
    rid = created["id"]

    client.post(
        f"/api/runs/{rid}/metrics",
        headers=hdr,
        json={"name": "loss", "value": 0.3, "step": 1, "expected_version": 1},
    )
    client.post(
        f"/api/runs/{rid}/artifacts",
        headers=hdr,
        json={
            "name": "model.bin",
            "uri": "s3://lab/model.bin",
            "content_sha256": sha("model-bin"),
            "media_type": "application/octet-stream",
            "expected_version": 2,
        },
    )
    client.post(
        f"/api/runs/{rid}/complete",
        headers=hdr,
        json={"result_summary": "完成", "expected_version": 3},
    )

    detail = client.get(f"/api/runs/{rid}", headers=hdr).json()
    timeline = client.get(f"/api/runs/{rid}/events", headers=hdr).json()
    assert detail["status"] == "completed"
    assert len(timeline) == 4

    txt = client.get(f"/api/runs/{rid}/report?format=txt", headers=hdr)
    body = txt.text
    assert txt.headers["x-event-count"] == str(len(timeline))
    # 状态 / 两枚指纹 / 事件摘要 / 指标 / 产物 全部与详情一致
    assert detail["status"] in body
    assert detail["dataset_content_sha256"] in body
    assert detail["code_commit_sha"] in body
    event_lines = [ln for ln in body.splitlines() if ln.startswith("v") and " | " in ln]
    assert len(event_lines) == len(timeline)
    assert detail["metrics_json"][0]["name"] in body
    assert detail["artifacts_json"][0]["name"] in body
    assert detail["artifacts_json"][0]["content_sha256"] in body

    # 审计员下载到的内容与研究员完全一致
    auditor = client.get(f"/api/runs/{rid}/report?format=txt", headers=_auth("auditor"))
    assert auditor.status_code == 200
    assert auditor.text == body

    # CSV 行数同样覆盖全部事件
    csv_body = client.get(f"/api/runs/{rid}/report?format=csv", headers=_auth("auditor")).text
    csv_events = [r for r in csv.reader(io.StringIO(csv_body.lstrip("﻿"))) if r and r[0] == "event"]
    assert len(csv_events) == len(timeline)
