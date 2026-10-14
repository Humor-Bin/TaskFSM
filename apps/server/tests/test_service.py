from datetime import timedelta

import pytest

from taskfsm.infrastructure.db import make_engine, make_session_factory
from taskfsm.domain.models import Base
from taskfsm.domain.service import TaskFSMService, DomainError, utcnow


@pytest.fixture()
def service():
    engine = make_engine('sqlite+pysqlite:///:memory:', testing=True)
    Base.metadata.create_all(engine)
    return TaskFSMService(make_session_factory(engine))


def test_agent_claim_artifact_review_complete_flow(service):
    agent = service.register_agent('Nova', 'codex', ['python', 'rag'])
    dep = service.create_task('准备数据', status='done')
    task = service.create_task('构建索引', status='ready', required_capabilities=['python'], dependency_ids=[dep.id])
    available = service.available_tasks(agent.id)
    assert [item.id for item in available] == [task.id]
    claim = service.claim_task(task.id, agent.id, lease_seconds=600)
    assert claim.task.status == 'in_progress'
    assert claim.lease.agent_id == agent.id
    assert claim.run.task_id == task.id
    artifact = service.submit_artifact(task.id, agent.id, 'report', 'memory://index-report')
    assert artifact.run_id == claim.run.id
    reviewed = service.request_review(task.id, agent.id)
    assert reviewed.status == 'review'
    service.submit_review(task.id, 'human:alice', 'approved', '通过')
    completed = service.complete_task(task.id, 'human:alice')
    assert completed.status == 'done'
    types = [event.event_type for event in service.list_events(limit=100)]
    for expected in ['agent.registered','task.created','task.claimed','artifact.created','task.review_requested','review.submitted','task.completed']:
        assert expected in types


def test_capability_filter_excludes_incompatible_task(service):
    agent = service.register_agent('Writer', 'custom', ['docs'])
    service.create_task('Python 工作', status='ready', required_capabilities=['python'])
    service.create_task('文档工作', status='ready', required_capabilities=['docs'])
    assert [task.title for task in service.available_tasks(agent.id)] == ['文档工作']


def test_dependency_guard_blocks_claim(service):
    agent = service.register_agent('Nova', 'codex', ['python'])
    dep = service.create_task('上游', status='todo')
    task = service.create_task('下游', status='ready', required_capabilities=['python'], dependency_ids=[dep.id])
    with pytest.raises(DomainError, match='依赖'):
        service.claim_task(task.id, agent.id)


def test_expired_lease_returns_task_to_ready_and_rejects_mutation(service):
    agent = service.register_agent('Nova', 'codex', ['python'])
    task = service.create_task('工作', status='ready', required_capabilities=['python'])
    claim = service.claim_task(task.id, agent.id, lease_seconds=1)
    with service.session() as session:
        lease = session.get(type(claim.lease), claim.lease.id)
        lease.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert service.sweep_expired_leases() == 1
    assert service.get_task(task.id).status == 'ready'
    with pytest.raises(DomainError, match='有效租约'):
        service.submit_artifact(task.id, agent.id, 'file', 'memory://late')


def test_review_cannot_complete_without_approval(service):
    agent = service.register_agent('Nova', 'codex', ['python'])
    task = service.create_task('工作', status='ready', required_capabilities=['python'])
    service.claim_task(task.id, agent.id)
    service.submit_artifact(task.id, agent.id, 'file', 'memory://a')
    service.request_review(task.id, agent.id)
    with pytest.raises(DomainError, match='审查批准'):
        service.complete_task(task.id, 'human:alice')
