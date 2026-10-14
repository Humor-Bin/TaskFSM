# TaskFSM

TaskFSM 是一个 **Agent 任务观测 + 可选调度控制平面**。它既能把 Agent 自己产生的任务、Plan、Session 和执行进展投影到统一界面，也能在需要自动化时由 TaskFSM 创建任务并调度 Agent 执行。

当前优先支持 **Codex CLI**。

## 两种运行模式

### Observe Mode（观察模式）

用户照常启动 Codex CLI，TaskFSM 扫描 `CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`，把原生 Codex Session 映射为只读的 Task/Run：

```text
Codex CLI（用户启动）
        ↓ rollout JSONL
Codex Observer
        ↓
TaskFSM Task / Run Projection
        ↓
Web 可视化
```

Observed 任务具有：

- `source = codex`
- `control_mode = observed`
- `external_id = Codex session id`
- 原生 Plan 快照
- 当前动作 / Session / Workspace / Runtime Event

**Observed 任务不会进入 TaskFSM 的领取队列，也不能被 TaskFSM 人工标记完成。** TaskFSM 在此模式只负责观察和统一投影。

### Managed Mode（管理模式）

TaskFSM 可以显式启动本机 Codex CLI：

```text
TaskFSM Task
   ↓ Claim + Lease + Run
CodexRuntimeManager
   ↓ codex exec --json
Codex CLI
   ↓ MCP
TaskFSM Progress / Artifact / Review
```

Managed 模式默认关闭。设置：

```bash
export TASKFSM_CODEX_MANAGED=1
```

然后通过：

```http
POST /api/tasks/{task_id}/codex/start
```

启动受管 Codex Run。CLI JSONL 只用于运行观测，**不会因为 Codex 输出“完成”就直接改变业务状态**。状态迁移仍由 TaskFSM FSM / Guard 裁决。

## Codex Plugin + MCP

仓库包含：

```text
integrations/codex-plugin/
  .codex-plugin/plugin.json
  .mcp.json
  skills/taskfsm-worker/SKILL.md

packages/taskfsm-mcp/
  taskfsm_mcp/server.py
```

安装本地 MCP 包：

```bash
pip install -e packages/taskfsm-mcp
```

TaskFSM Codex Plugin 使用当前 Codex 兼容插件布局，并把 `taskfsm-mcp` 作为 stdio MCP Server。Managed Runner 会把以下上下文注入 Codex 进程：

- `TASKFSM_TASK_ID`
- `TASKFSM_RUN_ID`
- `TASKFSM_AGENT_ID`
- `TASKFSM_AGENT_TOKEN`
- `TASKFSM_LEASE_ID`

MCP 工具目前包括：

- `get_current_task`
- `heartbeat`
- `report_progress`
- `submit_artifact`
- `request_review`

Skill 明确规定：Codex 内部 plan/todo 只是执行细节；TaskFSM 才是 Managed 任务生命周期的权威来源。

## 当前能力

- 中文运行控制台
- Observed / Managed 模式可视化
- Codex 原生 Session 自动发现与投影
- Codex Plan 快照解析
- 本地 Codex CLI Managed Runner
- FastAPI + SQLAlchemy 后端
- Task FSM / Guard
- Dependency / Capability matching
- Agent 注册与 Bearer Token
- Claim / Lease / Heartbeat / Run
- Progress / Artifact / Review / Complete
- Lease 过期回收
- Event Log + SSE
- Python Agent SDK
- TaskFSM MCP Server
- Codex Plugin / Skill
- SQLite 默认运行，支持 PostgreSQL
- Docker Compose 与 GitHub Actions CI

## 目录

```text
apps/
  web/                       # 中文运行控制台
  server/                    # TaskFSM API / FSM / Codex integration
packages/
  agent-sdk-python/          # 通用 Agent SDK
  taskfsm-mcp/               # Codex/Agent MCP tools
integrations/
  codex-plugin/              # Codex Plugin + TaskFSM worker Skill
deployments/docker/          # Dockerfile / Compose
docs/                        # 功能与设计文档
```

## 本地启动

Python 3.11+：

```bash
cd apps/server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export PYTHONPATH=.
python run.py
```

访问：

- Web：`http://127.0.0.1:8000/`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

### 同步本机 Codex Session

确保 TaskFSM 服务进程可以访问 Codex 的 home：

```bash
export CODEX_HOME=~/.codex
```

Web 点击“同步 Codex”，或：

```bash
curl -X POST http://127.0.0.1:8000/api/integrations/codex/sync \
  -H 'Content-Type: application/json' \
  -d '{"limit": 200}'
```

查看集成状态：

```bash
curl http://127.0.0.1:8000/api/integrations/codex/status
```

## 核心 API

通用 Agent：

- `POST /api/agents/register`
- `GET /api/agent/tasks/available`
- `POST /api/tasks/{id}/claim`
- `POST /api/leases/{id}/heartbeat`
- `POST /api/tasks/{id}/progress`
- `POST /api/tasks/{id}/artifacts`
- `POST /api/tasks/{id}/request-review`
- `POST /api/tasks/{id}/reviews`
- `POST /api/tasks/{id}/complete`

Codex：

- `GET /api/integrations/codex/status`
- `POST /api/integrations/codex/sync`
- `POST /api/tasks/{id}/codex/start`
- `POST /api/runs/{id}/codex/stop`

Realtime：

- `GET /api/dashboard`
- `GET /api/events`
- `GET /api/events/stream`

## 测试

```bash
cd apps/server && PYTHONPATH=. pytest -q
cd ../../packages/agent-sdk-python && PYTHONPATH=. pytest -q
cd ../../apps/web && npm test
pip install -e ../../packages/taskfsm-mcp
python -c "from taskfsm_mcp.server import mcp; assert mcp is not None"
```

## 核心设计原则

1. **观察与控制分离**：Observed Session 不被 TaskFSM 接管。
2. **执行与状态分离**：Codex CLI 日志是运行事实，不是业务状态命令。
3. **Managed 状态唯一入口**：Agent 只能通过 Action/MCP 请求迁移，FSM/Guard 决定结果。
4. **Agent 原生 Plan 保留**：内部 todo/plan 映射为 Run 执行细节，不强行转换成 TaskFSM 子任务。
5. **可观测事件优先**：展示工具、命令、Plan、Artifact、错误、Session 等外部可观察事实，不采集隐藏推理。
6. **调度是增强能力**：TaskFSM 可以从纯 Observer 渐进到 Orchestrator，而不要求所有 Agent 都由 TaskFSM 启动。
