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

    def create_task(self, title, description='', status='backlog', priority='medium', required_capabilities=None, dependency_ids=None, actor='human:system', task_id=None):
        with self.session() as s:
            task = Task(id=task_id, title=title, description=description, status=status, priority=priority, required_capabilities=list(required_capabilities or [])) if task_id else Task(title=title, description=description, status=status, priority=priority, required_capabilities=list(required_capabilities or []))
            s.add(task); s.flush()
            if dependency_ids:
                deps = list(s.scalars(select(Task).where(Task.id.in_(dependency_ids))))
                if len(deps) != len(set(dependency_ids)): raise DomainError('依赖任务不存在')
                task.dependencies = deps
            _ = list(task.dependencies)
            event = self._event(s, 'task.created', 'task', task.id, 'human', actor, {'title': title, 'status': status})
            s.commit(); self._publish_after(event); return task

    def list_tasks(self):
        with self.session() as s:
            tasks = list(s.scalars(select(Task).order_by(Task.created_at)).unique())
            for task in tasks:
                _ = list(task.dependencies)
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
            tasks = list(s.scalars(select(Task).where(Task.status == 'ready').order_by(Task.created_at)).unique())
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
            if not set(task.required_capabilities or []).issubset(set(agent.capabilities or [])):
                raise DomainError('Agent 能力不满足任务要求')
            try:
                task.status = apply_action(TransitionContext(task.status, self._dependencies_done(task), False, False, False), 'claim')
            except TransitionError as e: raise DomainError(str(e)) from e
            run = Run(task_id=task.id, agent_id=agent.id)
            s.add(run); s.flush()
            lease = Lease(task_id=task.id, agent_id=agent.id, run_id=run.id, expires_at=utcnow()+timedelta(seconds=lease_seconds))
            s.add(lease)
            task.assignee_type='agent'; task.assignee_id=agent.id; task.current_action='Agent 已领取任务'
            event = self._event(s, 'task.claimed', 'task', task.id, 'agent', agent.id, {'run_id': run.id, 'lease_id': lease.id, 'lease_seconds': lease_seconds})
            s.commit(); self._publish_after(event); return ClaimResult(task, lease, run)

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
            if decision=='changes_requested':
                task.status='in_progress'; task.current_action='审查要求修改'
            elif decision=='rejected':
                task.status='blocked'; task.current_action='审查拒绝'
            event=self._event(s,'review.submitted','task',task_id,'human',reviewer,{'decision':decision,'reason':reason})
            s.commit(); self._publish_after(event); return review

    def complete_task(self, task_id, actor):
        with self.session() as s:
            task=s.get(Task,task_id)
            if not task: raise DomainError('任务不存在')
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
                    if task and task.status=='in_progress': task.status='ready'; task.assignee_id=None; task.assignee_type=None; task.current_action='租约过期，等待重新领取'
                    run=s.get(Run,lease.run_id) if lease.run_id else None
                    if run: run.status='expired'; run.ended_at=now
                    self._event(s,'lease.expired','task',lease.task_id,'system','taskfsm',{'lease_id':lease.id}); changed+=1
            s.commit()
        return changed

    def list_events(self, limit=100):
        with self.session() as s:
            return list(s.scalars(select(Event).order_by(Event.id.desc()).limit(limit)))[::-1]
