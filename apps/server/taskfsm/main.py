from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from taskfsm.domain.models import Agent, Artifact, Base, Lease, Review, Run, Task
from taskfsm.domain.service import DomainError, TaskFSMService
from taskfsm.infrastructure.db import make_engine, make_session_factory
from taskfsm.integrations.codex import CodexObserver, CodexRuntimeManager
from taskfsm.realtime.broker import InMemoryBroker


class TaskCreate(BaseModel):
    title: str
    description: str = ''
    status: str = 'backlog'
    priority: str = 'medium'
    required_capabilities: list[str] = Field(default_factory=list)
    dependency_ids: list[str] = Field(default_factory=list)


class AgentRegister(BaseModel):
    name: str
    kind: str = 'generic'
    capabilities: list[str] = Field(default_factory=list)


class ClaimIn(BaseModel):
    agent_id: str
    lease_seconds: int = 600


class LeaseHeartbeatIn(BaseModel):
    agent_id: str
    extend_seconds: int = 600


class ProgressIn(BaseModel):
    agent_id: str
    progress: int
    current_action: str


class ArtifactIn(BaseModel):
    agent_id: str
    type: str
    uri: str
    metadata: dict = Field(default_factory=dict)


class AgentActionIn(BaseModel):
    agent_id: str


class ReviewIn(BaseModel):
    reviewer: str
    decision: str
    reason: str = ''


class CompleteIn(BaseModel):
    actor: str


class CodexStartIn(BaseModel):
    workspace: str
    prompt: str | None = None
    lease_seconds: int = 1800


class CodexSyncIn(BaseModel):
    limit: int = 200


def dt(value):
    return value.isoformat() if value else None


def task_dict(task: Task):
    return {
        'id': task.id, 'title': task.title, 'description': task.description, 'status': task.status,
        'priority': task.priority, 'assignee_type': task.assignee_type, 'assignee_id': task.assignee_id,
        'required_capabilities': task.required_capabilities or [], 'dependency_ids': [d.id for d in task.dependencies],
        'progress': task.progress, 'current_action': task.current_action,
        'source': task.source, 'control_mode': task.control_mode, 'external_id': task.external_id,
        'source_metadata': task.source_metadata or {},
        'created_at': dt(task.created_at), 'updated_at': dt(task.updated_at),
    }


def agent_dict(agent: Agent, include_token=False):
    data = {'id': agent.id, 'name': agent.name, 'kind': agent.kind, 'capabilities': agent.capabilities or [], 'last_heartbeat_at': dt(agent.last_heartbeat_at)}
    if include_token and hasattr(agent, 'api_token'): data['api_token'] = agent.api_token
    return data


def run_dict(run: Run):
    return {
        'id': run.id, 'task_id': run.task_id, 'agent_id': run.agent_id, 'status': run.status,
        'source': run.source, 'control_mode': run.control_mode, 'external_session_id': run.external_session_id,
        'workspace': run.workspace, 'pid': run.pid, 'plan_snapshot': run.plan_snapshot or [],
        'current_event': run.current_event or {}, 'last_event_at': dt(run.last_event_at),
        'started_at': dt(run.started_at), 'ended_at': dt(run.ended_at),
    }


def event_dict(event):
    return {'id': event.id, 'event_type': event.event_type, 'entity_type': event.entity_type, 'entity_id': event.entity_id,
            'actor_type': event.actor_type, 'actor_id': event.actor_id, 'payload': event.payload or {}, 'created_at': dt(event.created_at)}


def create_app(database_url: str | None = None, testing: bool = False):
    database_url = database_url or os.getenv('DATABASE_URL', 'sqlite+pysqlite:///./taskfsm.db')
    engine = make_engine(database_url, testing=testing)
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    broker = InMemoryBroker()

    def sink(event): broker.publish(event_dict(event))

    service = TaskFSMService(sessions, event_sink=sink)
    codex_observer = CodexObserver(service)
    codex_runtime = CodexRuntimeManager(service, command=os.getenv('TASKFSM_CODEX_COMMAND', 'codex'))
    if not testing and os.getenv('TASKFSM_DEMO_SEED', '0') == '1':
        from taskfsm.seed import seed_demo
        seed_demo(service)

    app = FastAPI(title='TaskFSM API', version='0.3.0')
    app.state.service = service
    app.state.sessions = sessions
    app.state.broker = broker
    app.state.codex_observer = codex_observer
    app.state.codex_runtime = codex_runtime
    app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

    @app.exception_handler(DomainError)
    async def domain_error_handler(_, exc: DomainError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    def require_agent(agent_id: str, authorization: str | None):
        token = authorization.removeprefix('Bearer ').strip() if authorization and authorization.startswith('Bearer ') else None
        if not service.authenticate_agent(agent_id, token): raise HTTPException(status_code=401, detail='Agent 凭据无效')

    @app.get('/health')
    def health(): return {'status': 'ok'}

    @app.post('/api/tasks')
    def create_task(payload: TaskCreate): return task_dict(service.create_task(**payload.model_dump()))

    @app.get('/api/tasks')
    def list_tasks(): return [task_dict(t) for t in service.list_tasks()]

    @app.get('/api/tasks/{task_id}')
    def get_task(task_id: str): return task_dict(service.get_task(task_id))

    @app.post('/api/agents/register')
    def register(payload: AgentRegister): return agent_dict(service.register_agent(payload.name, payload.kind, payload.capabilities), include_token=True)

    @app.post('/api/agents/{agent_id}/heartbeat')
    def agent_heartbeat(agent_id: str, authorization: str | None = Header(default=None)):
        require_agent(agent_id, authorization); return agent_dict(service.agent_heartbeat(agent_id))

    @app.get('/api/agent/tasks/available')
    def available(agent_id: str = Query(...), authorization: str | None = Header(default=None)):
        require_agent(agent_id, authorization); return [task_dict(t) for t in service.available_tasks(agent_id)]

    @app.post('/api/tasks/{task_id}/claim')
    def claim(task_id: str, payload: ClaimIn, authorization: str | None = Header(default=None)):
        require_agent(payload.agent_id, authorization)
        result = service.claim_task(task_id, payload.agent_id, payload.lease_seconds)
        return {'task': task_dict(result.task), 'lease': {'id': result.lease.id, 'agent_id': result.lease.agent_id, 'task_id': result.lease.task_id, 'run_id': result.lease.run_id, 'expires_at': dt(result.lease.expires_at)}, 'run': run_dict(result.run)}

    @app.post('/api/leases/{lease_id}/heartbeat')
    def lease_heartbeat(lease_id: str, payload: LeaseHeartbeatIn, authorization: str | None = Header(default=None)):
        require_agent(payload.agent_id, authorization)
        lease = service.lease_heartbeat(lease_id, payload.agent_id, payload.extend_seconds)
        return {'id': lease.id, 'expires_at': dt(lease.expires_at), 'last_heartbeat_at': dt(lease.last_heartbeat_at)}

    @app.post('/api/tasks/{task_id}/progress')
    def progress(task_id: str, payload: ProgressIn, authorization: str | None = Header(default=None)):
        require_agent(payload.agent_id, authorization); return task_dict(service.report_progress(task_id, payload.agent_id, payload.progress, payload.current_action))

    @app.post('/api/tasks/{task_id}/artifacts')
    def artifact(task_id: str, payload: ArtifactIn, authorization: str | None = Header(default=None)):
        require_agent(payload.agent_id, authorization)
        item = service.submit_artifact(task_id, payload.agent_id, payload.type, payload.uri, payload.metadata)
        return {'id': item.id, 'task_id': item.task_id, 'run_id': item.run_id, 'type': item.type, 'uri': item.uri, 'metadata': item.metadata_json}

    @app.post('/api/tasks/{task_id}/request-review')
    def request_review(task_id: str, payload: AgentActionIn, authorization: str | None = Header(default=None)):
        require_agent(payload.agent_id, authorization); return task_dict(service.request_review(task_id, payload.agent_id))

    @app.post('/api/tasks/{task_id}/reviews')
    def review(task_id: str, payload: ReviewIn):
        item = service.submit_review(task_id, payload.reviewer, payload.decision, payload.reason)
        return {'id': item.id, 'task_id': item.task_id, 'reviewer': item.reviewer, 'decision': item.decision, 'reason': item.reason}

    @app.post('/api/tasks/{task_id}/complete')
    def complete(task_id: str, payload: CompleteIn): return task_dict(service.complete_task(task_id, payload.actor))

    @app.get('/api/integrations/codex/status')
    def codex_status():
        return {
            'sessions_root': str(codex_observer.sessions_root),
            'sessions_root_exists': codex_observer.sessions_root.exists(),
            'active_window_seconds': codex_observer.active_window_seconds,
            'command': codex_runtime.command,
            'command_available': codex_runtime.available,
            'managed_enabled': os.getenv('TASKFSM_CODEX_MANAGED', '0') == '1',
            'active_run_ids': codex_runtime.active_run_ids(),
        }

    @app.post('/api/integrations/codex/sync')
    def codex_sync(payload: CodexSyncIn): return codex_observer.sync(payload.limit)

    @app.post('/api/tasks/{task_id}/codex/start')
    def codex_start(task_id: str, payload: CodexStartIn):
        result = codex_runtime.start(task_id, payload.workspace, payload.prompt, payload.lease_seconds)
        return {'task': task_dict(result.task), 'run': run_dict(result.run), 'lease': {'id': result.lease.id, 'expires_at': dt(result.lease.expires_at)}}

    @app.post('/api/runs/{run_id}/codex/stop')
    def codex_stop(run_id: str):
        if not codex_runtime.stop(run_id): raise HTTPException(status_code=404, detail='没有正在运行的本地 Codex 进程')
        return {'stopping': True, 'run_id': run_id}

    @app.post('/api/internal/leases/sweep')
    def sweep(): return {'expired': service.sweep_expired_leases()}

    @app.get('/api/events')
    def events(limit: int = 100): return [event_dict(e) for e in service.list_events(limit)]

    @app.get('/api/dashboard')
    def dashboard():
        tasks = service.list_tasks()
        managed_summary = {key: 0 for key in ['backlog','todo','ready','in_progress','review','blocked','done']}
        source_summary = {'observed': 0, 'managed': 0}
        for task in tasks:
            source_summary[task.control_mode] = source_summary.get(task.control_mode, 0) + 1
            if task.control_mode == 'managed':
                managed_summary[task.status] = managed_summary.get(task.status, 0) + 1
        with sessions() as s:
            agents = list(s.scalars(select(Agent).order_by(Agent.name)))
            leases = list(s.scalars(select(Lease).where(Lease.active.is_(True))))
            runs = list(s.scalars(select(Run).order_by(Run.started_at.desc()).limit(200)))
            artifacts = list(s.scalars(select(Artifact).order_by(Artifact.created_at.desc()).limit(50)))
            reviews = list(s.scalars(select(Review).order_by(Review.created_at.desc()).limit(50)))
        observed_runtime_summary = {'active': 0, 'waiting': 0, 'ended': 0, 'error': 0}
        for run in runs:
            if run.control_mode != 'observed':
                continue
            key = {'running': 'active', 'waiting': 'waiting', 'ended': 'ended', 'error': 'error'}.get(run.status, 'ended')
            observed_runtime_summary[key] = observed_runtime_summary.get(key, 0) + 1
        return {
            'summary': managed_summary,
            'managed_summary': managed_summary,
            'observed_runtime_summary': observed_runtime_summary,
            'source_summary': source_summary,
            'tasks': [task_dict(t) for t in tasks], 'agents': [agent_dict(a) for a in agents],
            'active_leases': [{'id': l.id, 'task_id': l.task_id, 'agent_id': l.agent_id, 'run_id': l.run_id, 'expires_at': dt(l.expires_at)} for l in leases],
            'runs': [run_dict(r) for r in runs],
            'artifacts': [{'id': a.id, 'task_id': a.task_id, 'run_id': a.run_id, 'type': a.type, 'uri': a.uri, 'created_by': a.created_by} for a in artifacts],
            'reviews': [{'id': r.id, 'task_id': r.task_id, 'reviewer': r.reviewer, 'decision': r.decision, 'reason': r.reason} for r in reviews],
            'events': [event_dict(e) for e in service.list_events(100)],
            'integrations': {'codex': {'sessions_root': str(codex_observer.sessions_root), 'command_available': codex_runtime.available, 'managed_enabled': os.getenv('TASKFSM_CODEX_MANAGED', '0') == '1'}},
        }

    @app.get('/api/events/stream')
    async def event_stream():
        async def stream():
            async with broker.subscribe() as queue:
                yield ': connected\n\n'
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ': keepalive\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control':'no-cache'})

    web_root = Path(__file__).resolve().parents[2] / 'web'
    if web_root.exists(): app.mount('/', StaticFiles(directory=str(web_root), html=True), name='web')
    return app


app = create_app()
