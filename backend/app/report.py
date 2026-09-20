"""单 Run 溯源报告生成：CSV / 纯文本，内容由后端从投影与 event_store 组装。"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from app.models import EventStore, RunProjection

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
TXT_MEDIA_TYPE = "text/plain; charset=utf-8"


def report_filename(proj: RunProjection, fmt: str) -> str:
    return f"run-{proj.id}-report.{fmt}"


def _iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _run_fields(proj: RunProjection) -> list[tuple[str, object]]:
    """与详情页一致的核心字段（含状态与两枚指纹）。"""
    return [
        ("run_id", str(proj.id)),
        ("project", proj.project),
        ("name", proj.name),
        ("status", proj.status),
        ("version", proj.version),
        ("dataset_content_sha256", proj.dataset_content_sha256),
        ("code_commit_sha", proj.code_commit_sha),
        ("started_by", proj.started_by),
        ("started_at", _iso(proj.started_at)),
        ("finished_at", _iso(proj.finished_at)),
        ("description", proj.description or ""),
        ("result_summary", proj.result_summary or ""),
        ("abort_reason", proj.abort_reason or ""),
    ]


def build_run_report_csv(proj: RunProjection, events: list[EventStore]) -> str:
    """分段 CSV：run 字段 / 事件摘要 / 指标 / 产物。带 BOM 便于 Excel 打开。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")

    writer.writerow(["section", "field", "value"])
    for key, value in _run_fields(proj):
        writer.writerow(["run", key, value])
    writer.writerow(["run", "event_count", len(events)])
    writer.writerow(["run", "metric_count", len(proj.metrics_json or [])])
    writer.writerow(["run", "artifact_count", len(proj.artifacts_json or [])])
    writer.writerow([])

    writer.writerow(["section", "version", "event_type", "actor", "occurred_at", "payload_json"])
    for ev in events:
        writer.writerow(
            [
                "event",
                ev.version,
                ev.event_type,
                ev.actor,
                _iso(ev.occurred_at),
                json.dumps(ev.payload_json, ensure_ascii=False, sort_keys=True),
            ]
        )
    writer.writerow([])

    writer.writerow(["section", "name", "value", "step", "recorded_at", "actor"])
    for m in proj.metrics_json or []:
        writer.writerow(
            ["metric", m.get("name"), m.get("value"), m.get("step"), m.get("recorded_at"), m.get("actor")]
        )
    writer.writerow([])

    writer.writerow(["section", "name", "uri", "content_sha256", "media_type", "attached_at", "actor"])
    for a in proj.artifacts_json or []:
        writer.writerow(
            [
                "artifact",
                a.get("name"),
                a.get("uri"),
                a.get("content_sha256"),
                a.get("media_type"),
                a.get("attached_at"),
                a.get("actor"),
            ]
        )

    # BOM 让 Excel 按 UTF-8 打开中文不错乱
    return "\ufeff" + buf.getvalue()


def build_run_report_txt(proj: RunProjection, events: list[EventStore]) -> str:
    """人类可读纯文本报告；事件/指标/产物条数与时间线、详情页一致。"""
    line = "-" * 64
    out: list[str] = []
    out.append("实验 Run 溯源报告")
    out.append("=" * 64)
    out.append(f"生成时间(UTC): {datetime.now(timezone.utc).isoformat()}")
    out.append("")
    out.append("基本信息")
    out.append(line)
    for key, value in _run_fields(proj):
        out.append(f"{key}: {value}")
    out.append("")

    metrics = proj.metrics_json or []
    artifacts = proj.artifacts_json or []

    out.append(f"事件摘要（共 {len(events)} 条）")
    out.append(line)
    for ev in events:
        out.append(f"v{ev.version} {ev.event_type} actor={ev.actor} occurred_at={_iso(ev.occurred_at)}")
        out.append(f"    payload: {json.dumps(ev.payload_json, ensure_ascii=False, sort_keys=True)}")
    out.append("")

    out.append(f"指标（共 {len(metrics)} 条）")
    out.append(line)
    for i, m in enumerate(metrics, start=1):
        out.append(
            f"[{i}] {m.get('name')} = {m.get('value')} @ step {m.get('step')}"
            f" (recorded_at={m.get('recorded_at')}, actor={m.get('actor')})"
        )
    out.append("")

    out.append(f"产物（共 {len(artifacts)} 条）")
    out.append(line)
    for i, a in enumerate(artifacts, start=1):
        out.append(f"[{i}] {a.get('name')}")
        out.append(f"    uri: {a.get('uri')}")
        out.append(f"    content_sha256: {a.get('content_sha256')}")
        out.append(f"    media_type: {a.get('media_type')}")
        out.append(f"    attached_at: {a.get('attached_at')} actor: {a.get('actor')}")
    out.append("")

    return "\n".join(out)
