# 科学实验溯源工作台（Experiment Provenance Workbench）

CQRS + Event Sourcing 全栈示例：命令追加 `event_store`，查询走投影表；Vue 前端查看 Run、事件时间线与血缘。

## How to Run

```bash
cd projects/03-experiment-provenance
docker compose up --build
```

> 镜像默认走 `docker.m.daocloud.io`（便于国内拉取）；前端 npm 使用 `npmmirror`。若你可直连 Docker Hub，可将 Dockerfile / compose 中的镜像前缀改回官方名。

首次启动会：

1. 拉起 PostgreSQL
2. 启动 FastAPI 后端并建表
3. `seed` 写入 2 条已完成 Run + 1 条进行中 Run
4. 构建并启动前端（nginx）

停止：

```bash
docker compose down
```

本地后端测试（可选，需 Python 3.11+）：

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

## Services / 端口

| 服务 | 地址 |
|------|------|
| Frontend | http://localhost:3173 |
| Backend API | http://localhost:8173 |
| PostgreSQL | localhost:54373 |

容器内：

- `db`：Postgres `provenance/provenance`，库名 `provenance`
- `backend`：Uvicorn `:8000`
- `seed`：一次性灌数后退出
- `frontend`：nginx `:80`，`/api` 反代到 backend

## 账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| researcher | lab123456 | 可发命令（Start/Metric/Artifact/Complete/Abort） |
| auditor | audit123456 | 只读事件与投影 |

## Verification

1. 打开 http://localhost:3173 ，使用 `researcher` / `lab123456` 登录
2. 在 Run 列表看到 seed 数据（含进行中与已完成）
3. 点击「新建 Run」，填写 project/name、dataset sha、code commit，启动
4. 在详情页记录指标、挂载产物，再 Complete（或 Abort）
5. 打开「事件时间线」确认 version 递增的原始事件
6. 打开「血缘」确认 code_commit、dataset 指纹、artifacts、metrics
7. 健康检查：`GET http://localhost:8173/api/health`
8. 用 `auditor` 登录：可看列表/事件/血缘，命令按钮不可用
9. 在任一已完成 Run 的详情页右侧侧栏点击「下载 CSV 报告」或「下载 TXT 报告」：
   文件由后端生成（`GET /api/runs/{id}/export?format=csv|txt`），包含状态、
   dataset/code 两枚指纹、事件摘要、指标与产物；打开文件核对字段与详情页一致、
   事件条数与时间线一致。审计员同样可下载（只读，不能改数据）。

终态或 `expected_version` 不匹配时，API 返回 **409**。

## 架构要点

- **命令**：`StartRun` / `RecordMetric` / `AttachArtifact` / `CompleteRun` / `AbortRun`
- **事件**：`RunStarted` / `MetricRecorded` / `ArtifactAttached` / `RunCompleted` / `RunAborted`
- **event_store**：`(aggregate_id, version)` 唯一；冲突 → 409
- **run_projections**：查询侧投影（状态、指标、产物等）
- **报告导出**：`GET /api/runs/{id}/export?format=csv|txt` 由后端读取投影 + event_store
  实时生成文件（`Content-Disposition: attachment`），前端只透传保存，不拼装内容；
  任意登录角色（含审计员）可下载，接口为只读 GET，不产生事件
