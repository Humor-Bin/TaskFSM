# TaskFSM

TaskFSM 是一个面向 AI Agent 协作、同时供人类监督的任务状态机与执行控制平面。

它不是让 Agent 直接修改任务状态的“AI 版看板”。TaskFSM 负责验证状态迁移、依赖、租约、执行 Run、产物和审查，并把每个关键动作记录为事件；Agent 只通过动作协议请求领取、心跳、上报进度、提交产物和申请审查。

## 当前版本包含

- 中文高保真运行控制台：状态流水线、Agent 拓扑、实时事件、任务详情
- FastAPI 模块化单体后端
- Task FSM 与 Guard：禁止 `in_progress -> done` 直达
- 依赖检查与 Agent capability 匹配
- Agent 注册与 Bearer Token 认证
- Task Claim、Lease、Heartbeat、Run
- Progress、Artifact、Review、Complete
- Lease 过期回收
- 持久化事件日志
- SSE 实时事件流
- Dashboard 聚合 API
- Python Agent SDK 与最小 Worker 示例
- SQLite 开箱即用，PostgreSQL 可通过 `DATABASE_URL` 切换
- Docker Compose 部署骨架（PostgreSQL + Redis + TaskFSM）

## 目录

```text
apps/
  web/                       # 中文运行控制台
  server/                    # FastAPI 控制平面
packages/
  agent-sdk-python/          # Agent 接入 SDK
deployments/docker/          # Dockerfile / Compose
docs/superpowers/specs/      # 架构规格
docs/superpowers/plans/      # 实现计划
```

## 本地启动

Python 3.11+：

```bash
cd apps/server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export TASKFSM_DEMO_SEED=1
export PYTHONPATH=.
python run.py
```

访问：

- Web：`http://127.0.0.1:8000/`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

默认数据库为当前目录下 `taskfsm.db`。设置 `DATABASE_URL` 可切换 PostgreSQL。

## Docker

```bash
cd deployments/docker
docker compose up --build
```

然后访问 `http://127.0.0.1:8000/`。

> Redis 已在 Compose 中预留。当前单实例 SSE 使用进程内 Broker；未来多实例部署时按 `realtime` 接口替换为 Redis Pub/Sub 或 NATS，不影响领域层。

## Agent 接入

```bash
cd packages/agent-sdk-python
pip install -e .
python example_worker.py
```

核心流程：

```python
client = TaskFSMClient('http://127.0.0.1:8000')
reg = client.register('Coder-01', 'codex', ['python', 'testing'])
agent_id = reg['id']
tasks = client.available_tasks(agent_id)
claim = client.claim(tasks[0]['id'], agent_id)
client.progress(tasks[0]['id'], agent_id, 50, '正在执行')
client.submit_artifact(tasks[0]['id'], agent_id, 'git_commit', 'git://abc123')
client.request_review(tasks[0]['id'], agent_id)
```

注册后 SDK 会自动保存服务端返回的 Agent Token，并在后续请求中携带 Bearer Token。

## 关键 API

- `POST /api/agents/register`
- `POST /api/agents/{id}/heartbeat`
- `GET /api/agent/tasks/available`
- `POST /api/tasks/{id}/claim`
- `POST /api/leases/{id}/heartbeat`
- `POST /api/tasks/{id}/progress`
- `POST /api/tasks/{id}/artifacts`
- `POST /api/tasks/{id}/request-review`
- `POST /api/tasks/{id}/reviews`
- `POST /api/tasks/{id}/complete`
- `GET /api/dashboard`
- `GET /api/events`
- `GET /api/events/stream`

## 测试

```bash
cd apps/server && PYTHONPATH=. pytest -q
cd ../../packages/agent-sdk-python && PYTHONPATH=. pytest -q
cd ../../apps/web && npm test
```

## 架构原则

1. Agent 不能直接写 `task.status`。
2. 所有状态变化必须通过 Action + Guard。
3. Claim 创建 Lease 与 Run；重试生成新的 Run。
4. 运行时写操作要求有效 Lease。
5. Artifact 是一等对象，不塞进评论。
6. Review 批准是进入 Done 的必要条件。
7. 成功的业务动作都写入 Event Log，并可实时推送给前端。

更多细节见 `docs/superpowers/specs/2026-10-13-taskfsm-platform-design.md`。
