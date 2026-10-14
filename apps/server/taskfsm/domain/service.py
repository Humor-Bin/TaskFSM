from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from sqlalchemy import select

from .models import Agent, Artifact, Event, Lease, Review, Run, Task
from .state_machine import TransitionContext, TransitionError, apply_action


def utcnow():
    return datetime.now(timezone.utc)


class DomainError(ValueError):
    pass


@dataclass
class ClaimResult:
    task: Task
    lease: Lease
    run: Run
    agent_id: str = ''
    agent_token: str = ''


class TaskFSMService:
    def __init__(self, session_factory, event_sink=None):
        self.session = session_factory
        self.event_sink = event_sink

    def _event(self, session, event_type, entity_type, entity_id, actor_type, actor_id, payload=None):
        event = Event(event_type=event_type, entity_type=entity_type, entity_id=entity_id,
                      actor_type=actor_type, actor_id=actor_id, payload=payload or {})
        session.add(event)
        session.flush()
        return event

    def _publish_after(self, event):
        if self.event_sink:
            self.event_sink(event)

    def register_agent(self, name, kind, capabilities):
        raw = secrets.token_urlsafe(24)
        with self.session() as s:
            agent = Agent(name=name, kind=kind, capabilities=list(capabilities), token_hash=hashlib.sha256(raw.encode()).hexdigest())
            s.add(agent); s.flush()
            event = self._event(s, 'agent.registered', 'agent', agent.id, 'agent', agent.id, {'name': name, 'kind': kind, 'capabilities': list(capabilities)})
            s.commit(); self._publish_after(event)
            agent.api_token = raw
            return agent

    def authenticate_agent(self, agent_id, token):
        if not token:
            return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.session() as s:
            agent = s.get(Agent, agent_id)
            return bool(agent and secrets.compare_digest(agent.token_hash, digest))

    def agent_heartbeat(self, agent_id):
        with self.session() as s:
            agent = s.get(Agent, agent_id)
            if not agent: raise DomainError('Agent 不存在')
            agent.last_heartbeat_at = utcnow()
            event = self._event(s, 'agent.heartbeat', 'agent', agent.id, 'agent', agent.id)
            s.commit(); self._publish_after(event); return agent

    def create_task(self, title, description='', status='backlog', priority='medium', required_capabilities=None,
                    dependency_ids=None, actor='human:system', task_id=None, source='taskfsm', control_mode='managed',
                    external_id=None, source_metadata=None):
        with self.session() as s:
            kwargs = dict(title=title, description=description, status=status, priority=priority,
                          required_capabilities=list(required_capabilities or []), source=source,
                          control_mode=control_mode, external_id=external_id, source_metadata=source_metadata or {})
            task = Task(id=task_id, **kwargs) if task_id else Task(**kwargs)
            s.add(task); s.flush()
            if dependency_ids:
                deps = list(s.scalars(select(Task).where(Task.id.in_(dependency_ids))))
                if len(deps) != len(set(dependency_ids)): raise DomainError('依赖任务不存在')
                task.dependencies = deps
            _ = list(task.dependencies)
            event = self._event(s, 'task.created', 'task', task.id, 'human', actor,
                                {'title': title, 'status': status, 'source': source, 'control_mode': control_mode})
            s.commit(); self._publish_after(event); return task

    def list_tasks(self):
        with self.session() as s:
            tasks = list(s.scalars(select(Task).order_by(Task.created_at)).unique())
            for task in tasks: _ = list(task.dependencies)
            return tasks

    def get_task(self, task_id):
        with self.session() as s:
            task = s.get(Task, task_id)
            if not task: raise DomainError('任务不存在')
            _ = list(task.dependencies)
            return task

    def _dependencies_done(self, task):
        return all(dep.status == 'done' for dep in task.dependencies)

    def available_tasks(self, agent_id):
        with self.session() as s:
            agent = s.get(Agent, agent_id)
            if not agent: raise DomainError('Agent 不存在')
            capabilities = set(agent.capabilities or [])
            tasks = list(s.scalars(select(Task).where(Task.status == 'ready', Task.control_mode == 'managed').order_by(Task.created_at)).unique())
            return [t for t in tasks if set(t.required_capabilities or []).issubset(capabilities) and self._dependencies_done(t)]

    def _active_lease(self, s, task_id, agent_id=None):
        q = select(Lease).where(Lease.task_id == task_id, Lease.active.is_(True)).order_by(Lease.created_at.desc())
        lease = s.scalars(q).first()
        if not lease: return None
        expires = lease.expires_at
        if expires.tzinfo is None: expires = expires.replace(tzinfo=timezone.utc)
        if expires <= utcnow(): return None
        if agent_id and lease.agent_id != agent_id: return None
        return lease

    def claim_task(self, task_id, agent_id, lease_seconds=600):
        with self.session() as s:
            task, agent = s.get(Task, task_id), s.get(Agent, agent_id)
            if not task or not agent: raise DomainError('任务或 Agent 不存在')
            if task.control_mode != 'managed': raise DomainError('Observed 任务不能被 TaskFSM 领取')
            if not set(task.required_capabilities or []).issubset(set(agent.capabilities or [])):
                raise DomainError('Agent 能力不满足任务要求')
            try:
                task.status = apply_action(TransitionContext(task.status, self._dependencies_done(task), False, False, False), 'claim')
            except TransitionError as e: raise DomainError(str(e)) from e
            run = Run(task_id=task.id, agent_id=agent.id, source=task.source, control_mode='managed')
            s.add(run); s.flush()
            lease = Lease(task_id=task.id, agent_id=agent.id, run_id=run.id, expires_at=utcnow()+timedelta(seconds=lease_seconds))
            s.add(lease)
            task.assignee_type='agent'; task.assignee_id=agent.id; task.current_action='Agent 已领取任务'
            event = self._event(s, 'task.claimed', 'task', task.id, 'agent', agent.id, {'run_id': run.id, 'lease_id': lease.id, 'lease_seconds': lease_seconds})
            s.commit(); self._publish_after(event); return ClaimResult(task, lease, run)

    def _ensure_internal_codex_agent(self):
        raw = secrets.token_urlsafe(24)
        with self.session() as s:
            agent = s.scalars(select(Agent).where(Agent.name == 'TaskFSM Codex')).first()
            if not agent:
                agent = Agent(name='TaskFSM Codex', kind='codex-cli', capabilities=['coding', 'git', 'testing'])
                s.add(agent); s.flush()
            agent.token_hash = hashlib.sha256(raw.encode()).hexdigest()
            agent.last_heartbeat_at = utcnow()
            agent_id = agent.id
            s.commit()
        return agent_id, raw

    def claim_task_for_codex(self, task_id, workspace, lease_seconds=1800):
        agent_id, raw = self._ensure_internal_codex_agent()
        result = self.claim_task(task_id, agent_id, lease_seconds)
        with self.session() as s:
            run = s.get(Run, result.run.id)
            run.source = 'codex'; run.control_mode = 'managed'; run.workspace = workspace
            task = s.get(Task, task_id)
            task.source_metadata = {**(task.source_metadata or {}), 'managed_by': 'codex-cli', 'workspace': workspace}
            event = self._event(s, 'codex.managed_started', 'run', run.id, 'system', 'taskfsm', {'task_id': task_id, 'workspace': workspace})
            s.commit(); self._publish_after(event)
        result.agent_id = agent_id
        result.agent_token = raw
        return result

    def attach_managed_process(self, run_id, pid):
        with self.session() as s:
            run = s.get(Run, run_id)
            if not run: raise DomainError('Run 不存在')
            run.pid = int(pid)
            event = self._event(s, 'codex.process_started', 'run', run.id, 'system', 'taskfsm', {'pid': int(pid)})
            s.commit(); self._publish_after(event); return run

    def ingest_codex_runtime_event(self, run_id, raw_event):
        with self.session() as s:
            run = s.get(Run, run_id)
            if not run: raise DomainError('Run 不存在')
            task = s.get(Task, run.task_id)
            event_type = str(raw_event.get('type') or 'codex.event')
            session_id = raw_event.get('thread_id') or raw_event.get('session_id')
            if session_id: run.external_session_id = str(session_id)
            message = raw_event.get('message') or raw_event.get('text') or ''
            item = raw_event.get('item') if isinstance(raw_event.get('item'), dict) else {}
            if not message: message = item.get('text') or item.get('type') or event_type
            run.current_event = {'type': event_type, 'message': str(message)[:500]}
            run.last_event_at = utcnow()
            if str(item.get('type', '')).lower() == 'plan' and item.get('text'):
                run.plan_snapshot = [line.strip() for line in str(item['text']).splitlines() if line.strip()]
            if task: task.current_action = str(message)[:300]
            event = self._event(s, 'codex.runtime_event', 'run', run.id, 'agent', run.agent_id,
                                {'task_id': run.task_id, 'codex_type': event_type, 'message': str(message)[:1000]})
            s.commit(); self._publish_after(event); return run

    def finish_managed_codex_run(self, run_id, exit_code):
        with self.session() as s:
            run = s.get(Run, run_id)
            if not run: return
            task = s.get(Task, run.task_id)
            run.status = 'finished' if exit_code == 0 else 'failed'; run.ended_at = utcnow()
            if task:
                if exit_code == 0:
                    task.current_action = 'Codex CLI 已结束，等待产物/审查动作'
                else:
                    try:
                        task.status = apply_action(TransitionContext(task.status, self._dependencies_done(task), bool(self._active_lease(s, task.id)), self._has_artifact(s, task.id), False), 'block')
                    except TransitionError:
                        pass
                    task.current_action = f'Codex CLI 异常退出（{exit_code}）'
            event = self._event(s, 'codex.process_exited', 'run', run.id, 'system', 'taskfsm', {'exit_code': exit_code})
            s.commit(); self._publish_after(event)

    def fail_managed_run(self, run_id, reason):
        with self.session() as s:
            run = s.get(Run, run_id)
            if not run: return
            run.status = 'failed'; run.ended_at = utcnow(); run.current_event = {'type': 'startup_error', 'message': reason}
            event = self._event(s, 'codex.start_failed', 'run', run.id, 'system', 'taskfsm', {'reason': reason})
            s.commit(); self._publish_after(event)

    def upsert_observed_codex_session(self, snapshot):
        with self.session() as s:
            agent = s.scalars(select(Agent).where(Agent.name == 'Codex Observer')).first()
            if not agent:
                agent = Agent(name='Codex Observer', kind='codex-cli', capabilities=['observe'], token_hash='')
                s.add(agent); s.flush()
            run = s.scalars(select(Run).where(Run.external_session_id == snapshot.session_id, Run.control_mode == 'observed')).first()
            desired_status = {'waiting': 'blocked', 'ended': 'done', 'error': 'blocked'}.get(snapshot.status, 'in_progress')
            metadata = {
                'rollout_path': snapshot.path,
                'cwd': snapshot.cwd,
                'session_id': snapshot.session_id,
                'workspace_name': snapshot.workspace_name,
                'task_intent': snapshot.task_intent,
                'runtime_status': snapshot.status,
                **(snapshot.metadata or {}),
            }
            if not run:
                task = Task(
                    title=snapshot.title, description='从 Codex 原生 Session 自动投影', status=desired_status,
                    priority='medium', assignee_type='agent', assignee_id=agent.id,
                    source='codex', control_mode='observed', external_id=snapshot.session_id,
                    current_action=snapshot.current_action, source_metadata=metadata,
                )
                s.add(task); s.flush()
                run = Run(
                    task_id=task.id, agent_id=agent.id, status=snapshot.status, source='codex', control_mode='observed',
                    external_session_id=snapshot.session_id, workspace=snapshot.cwd, plan_snapshot=list(snapshot.plan),
                    current_event={'type': 'observed', 'message': snapshot.current_action}, last_event_at=snapshot.last_event_at,
                )
                if snapshot.status == 'ended': run.ended_at = snapshot.last_event_at or utcnow()
                s.add(run); s.flush()
                event = self._event(s, 'codex.session_discovered', 'run', run.id, 'agent', agent.id,
                                    {'task_id': task.id, 'session_id': snapshot.session_id, 'workspace': snapshot.cwd,
                                     'task_intent': snapshot.task_intent, 'runtime_status': snapshot.status})
            else:
                task = s.get(Task, run.task_id)
                changed = run.status != snapshot.status or task.current_action != snapshot.current_action or list(run.plan_snapshot or []) != list(snapshot.plan) or task.title != snapshot.title
                run.status = snapshot.status; run.workspace = snapshot.cwd; run.plan_snapshot = list(snapshot.plan)
                run.current_event = {'type': 'observed', 'message': snapshot.current_action}; run.last_event_at = snapshot.last_event_at
                run.ended_at = (snapshot.last_event_at or utcnow()) if snapshot.status == 'ended' else None
                task.title = snapshot.title; task.status = desired_status; task.current_action = snapshot.current_action
                task.source_metadata = metadata
                event = self._event(s, 'codex.session_updated', 'run', run.id, 'agent', agent.id,
                                    {'task_id': task.id, 'session_id': snapshot.session_id, 'status': snapshot.status,
                                     'task_intent': snapshot.task_intent}) if changed else None
            _ = list(task.dependencies)
            s.commit()
            if event: self._publish_after(event)
            return task, run

    def lease_heartbeat(self, lease_id, agent_id, extend_seconds=600):
        with self.session() as s:
            lease = s.get(Lease, lease_id)
            if not lease or not lease.active or lease.agent_id != agent_id: raise DomainError('有效租约不存在')
            lease.last_heartbeat_at=utcnow(); lease.expires_at=utcnow()+timedelta(seconds=extend_seconds)
            event=self._event(s,'lease.heartbeat','lease',lease.id,'agent',agent_id,{'task_id':lease.task_id})
            s.commit(); self._publish_after(event); return lease

    def report_progress(self, task_id, agent_id, progress, current_action):
        with self.session() as s:
            task=s.get(Task,task_id); lease=self._active_lease(s,task_id,agent_id)
            if not task or not lease: raise DomainError('需要有效租约')
            task.progress=max(0,min(100,int(progress))); task.current_action=current_action
            _ = list(task.dependencies)
            event=self._event(s,'run.progress','task',task.id,'agent',agent_id,{'progress':task.progress,'current_action':current_action})
            s.commit(); self._publish_after(event); return task

    def submit_artifact(self, task_id, agent_id, artifact_type, uri, metadata=None):
        with self.session() as s:
            lease=self._active_lease(s,task_id,agent_id)
            if not lease: raise DomainError('提交产物需要有效租约')
            artifact=Artifact(task_id=task_id,run_id=lease.run_id,created_by=agent_id,type=artifact_type,uri=uri,metadata_json=metadata or {})
            s.add(artifact); s.flush()
            event=self._event(s,'artifact.created','task',task_id,'agent',agent_id,{'artifact_id':artifact.id,'type':artifact_type,'uri':uri})
            s.commit(); self._publish_after(event); return artifact

    def _has_artifact(self,s,task_id):
        return s.scalars(select(Artifact).where(Artifact.task_id==task_id)).first() is not None

    def request_review(self, task_id, agent_id):
        with self.session() as s:
            task=s.get(Task,task_id); lease=self._active_lease(s,task_id,agent_id)
            if not task or not lease: raise DomainError('提交审查需要有效租约')
            try:
                task.status=apply_action(TransitionContext(task.status,self._dependencies_done(task),True,self._has_artifact(s,task_id),False),'request_review')
            except TransitionError as e: raise DomainError(str(e)) from e
            lease.active=False
            run=s.get(Run,lease.run_id); run.status='awaiting_review'; run.ended_at=utcnow()
            task.current_action='等待审查'
            event=self._event(s,'task.review_requested','task',task.id,'agent',agent_id,{'run_id':run.id})
            s.commit(); self._publish_after(event); return task

    def submit_review(self, task_id, reviewer, decision, reason=''):
        if decision not in {'approved','changes_requested','rejected'}: raise DomainError('无效审查决定')
        with self.session() as s:
            task=s.get(Task,task_id)
            if not task or task.status!='review': raise DomainError('任务不在待审查状态')
            review=Review(task_id=task_id,reviewer=reviewer,decision=decision,reason=reason); s.add(review)
            if decision=='changes_requested': task.status='in_progress'; task.current_action='审查要求修改'
            elif decision=='rejected': task.status='blocked'; task.current_action='审查拒绝'
            event=self._event(s,'review.submitted','task',task_id,'human',reviewer,{'decision':decision,'reason':reason})
            s.commit(); self._publish_after(event); return review

    def complete_task(self, task_id, actor):
        with self.session() as s:
            task=s.get(Task,task_id)
            if not task: raise DomainError('任务不存在')
            if task.control_mode != 'managed': raise DomainError('Observed 任务由外部 Agent 状态驱动，不能由 TaskFSM 完成')
            approved=s.scalars(select(Review).where(Review.task_id==task_id,Review.decision=='approved').order_by(Review.created_at.desc())).first() is not None
            try:
                task.status=apply_action(TransitionContext(task.status,self._dependencies_done(task),False,self._has_artifact(s,task_id),approved),'complete')
            except TransitionError as e: raise DomainError(str(e)) from e
            task.progress=100; task.current_action='已完成'
            event=self._event(s,'task.completed','task',task.id,'human',actor)
            s.commit(); self._publish_after(event); return task

    def sweep_expired_leases(self):
        changed=0
        with self.session() as s:
            leases=list(s.scalars(select(Lease).where(Lease.active.is_(True))))
            now=utcnow()
            for lease in leases:
                expires=lease.expires_at if lease.expires_at.tzinfo else lease.expires_at.replace(tzinfo=timezone.utc)
                if expires <= now:
                    lease.active=False; task=s.get(Task,lease.task_id)
                    if task and task.status=='in_progress' and task.control_mode == 'managed':
                        task.status='ready'; task.assignee_id=None; task.assignee_type=None; task.current_action='租约过期，等待重新领取'
                    run=s.get(Run,lease.run_id) if lease.run_id else None
                    if run: run.status='expired'; run.ended_at=now
                    self._event(s,'lease.expired','task',lease.task_id,'system','taskfsm',{'lease_id':lease.id}); changed+=1
            s.commit()
        return changed

    def list_events(self, limit=100):
        with self.session() as s:
            return list(s.scalars(select(Event).order_by(Event.id.desc()).limit(limit)))[::-1]
