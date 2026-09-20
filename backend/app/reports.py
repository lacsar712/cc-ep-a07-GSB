"""服务端溯源报告生成（CSV / 纯文本）。

报告内容只来自持久化状态：`run_projections` 投影表与 `event_store` 事件流，
不接受任何调用方提供的字段，前端也无法拼接或篡改文件内容。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Iterable

from app.models import EventStore, RunProjection

STATUS_LABELS = {
    "running": "进行中",
    "completed": "已完成",
    "aborted": "已中止",
}


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat(sep=" ") if value else ""


def _status_label(status: str) -> str:
    label = STATUS_LABELS.get(status)
    return f"{status}（{label}）" if label else status


def _event_payload(event: EventStore) -> str:
    return json.dumps(event.payload_json, ensure_ascii=False, sort_keys=True)


def _metric_row(metric: dict[str, Any]) -> list[str]:
    return [
        str(metric.get("step", "")),
        str(metric.get("name", "")),
        str(metric.get("value", "")),
        str(metric.get("recorded_at", "") or ""),
        str(metric.get("actor", "") or ""),
    ]


def _artifact_row(artifact: dict[str, Any]) -> list[str]:
    return [
        str(artifact.get("name", "") or ""),
        str(artifact.get("uri", "") or ""),
        str(artifact.get("content_sha256", "") or ""),
        str(artifact.get("media_type", "") or ""),
        str(artifact.get("attached_at", "") or ""),
        str(artifact.get("actor", "") or ""),
    ]


def report_filename(proj: RunProjection, fmt: str) -> str:
    return f"run-report-{proj.id}.{fmt}"


def _meta_rows(proj: RunProjection, event_count: int) -> list[tuple[str, str]]:
    rows = [
        ("run_id", str(proj.id)),
        ("project", proj.project),
        ("name", proj.name),
        ("status", proj.status),
        ("status_label", STATUS_LABELS.get(proj.status, proj.status)),
        ("version", str(proj.version)),
        ("event_count", str(event_count)),
        ("dataset_content_sha256", proj.dataset_content_sha256),
        ("code_commit_sha", proj.code_commit_sha),
        ("started_by", proj.started_by),
        ("started_at", _fmt_dt(proj.started_at)),
        ("finished_at", _fmt_dt(proj.finished_at)),
        ("description", proj.description or ""),
        ("result_summary", proj.result_summary or ""),
        ("abort_reason", proj.abort_reason or ""),
        ("metric_count", str(len(proj.metrics_json or []))),
        ("artifact_count", str(len(proj.artifacts_json or []))),
    ]
    return rows


def render_csv_report(proj: RunProjection, events: Iterable[EventStore]) -> str:
    events = list(events)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    writer.writerow(["# 科学实验溯源报告（服务端生成）"])
    writer.writerow(["section", "field", "value"])
    for field, value in _meta_rows(proj, len(events)):
        writer.writerow(["meta", field, value])

    writer.writerow([])
    writer.writerow(
        ["section", "version", "event_type", "actor", "occurred_at", "payload_json"]
    )
    for event in events:
        writer.writerow(
            [
                "event",
                event.version,
                event.event_type,
                event.actor,
                _fmt_dt(event.occurred_at),
                _event_payload(event),
            ]
        )

    writer.writerow([])
    writer.writerow(["section", "step", "name", "value", "recorded_at", "actor"])
    for metric in proj.metrics_json or []:
        writer.writerow(["metric", *_metric_row(metric)])

    writer.writerow([])
    writer.writerow(
        [
            "section",
            "name",
            "uri",
            "content_sha256",
            "media_type",
            "attached_at",
            "actor",
        ]
    )
    for artifact in proj.artifacts_json or []:
        writer.writerow(["artifact", *_artifact_row(artifact)])

    return buf.getvalue()


def render_text_report(proj: RunProjection, events: Iterable[EventStore]) -> str:
    events = list(events)
    metrics = proj.metrics_json or []
    artifacts = proj.artifacts_json or []

    lines: list[str] = []
    lines.append("科学实验溯源报告（服务端生成）")
    lines.append("=" * 60)
    lines.append("")
    lines.append("[基本信息]")
    lines.append(f"Run ID: {proj.id}")
    lines.append(f"项目: {proj.project}")
    lines.append(f"名称: {proj.name}")
    lines.append(f"状态: {_status_label(proj.status)}")
    lines.append(f"版本: {proj.version}（事件流共 {len(events)} 条）")
    lines.append(f"发起人: {proj.started_by}")
    lines.append(f"开始时间: {_fmt_dt(proj.started_at)}")
    lines.append(f"结束时间: {_fmt_dt(proj.finished_at) or '—'}")
    lines.append("")
    lines.append("[指纹]")
    lines.append(f"dataset_content_sha256: {proj.dataset_content_sha256}")
    lines.append(f"code_commit_sha:       {proj.code_commit_sha}")
    if proj.description:
        lines.append("")
        lines.append(f"描述: {proj.description}")
    if proj.result_summary:
        lines.append(f"结果摘要: {proj.result_summary}")
    if proj.abort_reason:
        lines.append(f"中止原因: {proj.abort_reason}")

    lines.append("")
    lines.append(f"[事件摘要] 共 {len(events)} 条（与事件时间线一致）")
    lines.append("-" * 60)
    for event in events:
        lines.append(
            f"v{event.version} | {event.event_type} | actor={event.actor} "
            f"| {_fmt_dt(event.occurred_at)}"
        )
        lines.append(f"    payload: {_event_payload(event)}")

    lines.append("")
    lines.append(f"[指标] 共 {len(metrics)} 条")
    lines.append("-" * 60)
    if metrics:
        lines.append("step\tname\tvalue\trecorded_at\tactor")
        for row in (_metric_row(m) for m in metrics):
            lines.append("\t".join(row))
    else:
        lines.append("（无）")

    lines.append("")
    lines.append(f"[产物] 共 {len(artifacts)} 条")
    lines.append("-" * 60)
    if artifacts:
        lines.append("name\turi\tcontent_sha256\tmedia_type\tattached_at\tactor")
        for row in (_artifact_row(a) for a in artifacts):
            lines.append("\t".join(row))
    else:
        lines.append("（无）")

    lines.append("")
    return "\n".join(lines)
