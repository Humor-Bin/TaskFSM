import json
from pathlib import Path

from taskfsm.domain.models import Base, Run
from taskfsm.domain.service import TaskFSMService
from taskfsm.infrastructure.db import make_engine, make_session_factory
from taskfsm.integrations.codex import CodexRolloutParser, CodexObserver


def make_service(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}", testing=True)
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    return TaskFSMService(sessions), sessions


def write_rollout(path: Path):
    rows = [
        {'timestamp':'2026-10-14T06:00:00Z','type':'session_meta','payload':{'id':'sess-123','cwd':'/repo/demo','source':'cli'}},
        {'timestamp':'2026-10-14T06:00:01Z','type':'event_msg','payload':{'type':'user_message','message':'实现登录接口'}},
        {'timestamp':'2026-10-14T06:00:02Z','type':'event_msg','payload':{'type':'item_completed','item':{'type':'Plan','text':'1. 阅读代码\n2. 修改认证\n3. 运行测试'}}},
        {'timestamp':'2026-10-14T06:00:03Z','type':'event_msg','payload':{'type':'agent_message','message':'我正在修改认证逻辑。'}},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')


def test_rollout_parser_extracts_session_plan_and_current_action(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-sess-123.jsonl'
    write_rollout(rollout)
    snap = CodexRolloutParser().parse(rollout)
    assert snap.session_id == 'sess-123'
    assert snap.cwd == '/repo/demo'
    assert snap.title == '实现登录接口'
    assert snap.plan == ['阅读代码', '修改认证', '运行测试']
    assert snap.current_action == '我正在修改认证逻辑。'


def test_observer_upserts_one_task_and_run_for_same_codex_session(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-sess-123.jsonl'
    write_rollout(rollout)
    service, sessions = make_service(tmp_path)
    observer = CodexObserver(service, sessions_root=tmp_path / 'sessions')

    first = observer.sync()
    second = observer.sync()

    assert first['discovered'] == 1
    assert second['discovered'] == 1
    tasks = service.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].source == 'codex'
    assert tasks[0].control_mode == 'observed'
    assert tasks[0].external_id == 'sess-123'
    with sessions() as s:
        runs = list(s.query(Run).all())
        assert len(runs) == 1
        assert runs[0].external_session_id == 'sess-123'
        assert runs[0].control_mode == 'observed'
        assert runs[0].plan_snapshot == ['阅读代码', '修改认证', '运行测试']


def test_managed_codex_runtime_event_does_not_bypass_task_fsm(tmp_path):
    service, sessions = make_service(tmp_path)
    task = service.create_task('受管任务', status='ready', required_capabilities=['coding'])
    claim = service.claim_task_for_codex(task.id, workspace='/repo/demo')
    assert claim.task.status == 'in_progress'

    service.ingest_codex_runtime_event(claim.run.id, {
        'type': 'turn.completed',
        'message': '任务完成',
        'session_id': 'managed-session-1',
    })

    refreshed = service.get_task(task.id)
    assert refreshed.status == 'in_progress'
    with sessions() as s:
        run = s.get(Run, claim.run.id)
        assert run.external_session_id == 'managed-session-1'
        assert run.current_event['type'] == 'turn.completed'
