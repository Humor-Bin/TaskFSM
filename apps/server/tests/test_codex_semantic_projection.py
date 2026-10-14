import json
import os
import time
from pathlib import Path

from taskfsm.domain.models import Base, Run
from taskfsm.domain.service import TaskFSMService
from taskfsm.infrastructure.db import make_engine, make_session_factory
from taskfsm.integrations.codex import CodexObserver, CodexRolloutParser


def make_service(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'semantic.db'}", testing=True)
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    return TaskFSMService(sessions), sessions


def write_rows(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')


def test_parser_exposes_task_intent_workspace_and_human_activity(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-human-1.jsonl'
    write_rows(rollout, [
        {'timestamp':'2026-10-14T08:00:00Z','type':'session_meta','payload':{'id':'human-1','cwd':'/home/user/Project/DataLabeling','source':'cli'}},
        {'timestamp':'2026-10-14T08:00:01Z','type':'event_msg','payload':{'type':'user_message','message':'请修复数据导入时 CSV 字段映射错误，并运行测试验证。'}},
        {'timestamp':'2026-10-14T08:00:02Z','type':'event_msg','payload':{'type':'item_completed','item':{'type':'Plan','text':'1. 阅读导入代码\n2. 修复字段映射\n3. 运行测试'}}},
        {'timestamp':'2026-10-14T08:00:03Z','type':'event_msg','payload':{'type':'item_started','item':{'type':'command_execution','command':'pytest tests/test_importer.py -q'}}},
    ])

    snap = CodexRolloutParser().parse(rollout)

    assert snap.task_intent == '请修复数据导入时 CSV 字段映射错误，并运行测试验证。'
    assert snap.title == '修复数据导入时 CSV 字段映射错误，并运行测试验证'
    assert snap.workspace_name == 'DataLabeling'
    assert snap.current_action == '正在执行命令：pytest tests/test_importer.py -q'
    assert snap.plan == ['阅读导入代码', '修复字段映射', '运行测试']


def test_parser_supports_current_codex_response_item_schema(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-response-item.jsonl'
    write_rows(rollout, [
        {'timestamp':'2026-10-14T08:20:00Z','type':'session_meta','payload':{'id':'response-item-1','cwd':'/home/user/Project/ServerManager','source':'cli'}},
        {'timestamp':'2026-10-14T08:20:01Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'检查 ServerManager 的部署流程并修复启动错误'}]}},
        {'timestamp':'2026-10-14T08:20:02Z','type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'我先检查启动脚本和服务配置。'}]}},
        {'timestamp':'2026-10-14T08:20:03Z','type':'response_item','payload':{'type':'custom_tool_call','name':'exec','input':'pytest tests/test_server.py -q'}},
    ])

    snap = CodexRolloutParser().parse(rollout)

    assert snap.task_intent == '检查 ServerManager 的部署流程并修复启动错误'
    assert snap.title == '检查 ServerManager 的部署流程并修复启动错误'
    assert snap.workspace_name == 'ServerManager'
    assert snap.current_action == '正在执行工具：exec · pytest tests/test_server.py -q'


def test_parser_ignores_environment_context_as_task_intent(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-context.jsonl'
    write_rows(rollout, [
        {'timestamp':'2026-10-14T08:25:00Z','type':'session_meta','payload':{'id':'context-1','cwd':'/repo/demo','source':'cli'}},
        {'timestamp':'2026-10-14T08:25:01Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'<environment_context>\n<cwd>/repo/demo</cwd>\n<shell>bash</shell>\n</environment_context>'}]}},
        {'timestamp':'2026-10-14T08:25:02Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'重构任务状态投影逻辑'}]}},
    ])

    snap = CodexRolloutParser().parse(rollout)

    assert snap.task_intent == '重构任务状态投影逻辑'
    assert snap.title == '重构任务状态投影逻辑'


def test_observer_marks_stale_session_ended_instead_of_running(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-stale-1.jsonl'
    write_rows(rollout, [
        {'timestamp':'2026-10-14T06:00:00Z','type':'session_meta','payload':{'id':'stale-1','cwd':'/repo/old','source':'cli'}},
        {'timestamp':'2026-10-14T06:00:01Z','type':'event_msg','payload':{'type':'user_message','message':'整理旧代码'}},
        {'timestamp':'2026-10-14T06:00:02Z','type':'event_msg','payload':{'type':'agent_message','message':'整理完成。'}},
    ])
    old = time.time() - 3600
    os.utime(rollout, (old, old))
    service, sessions = make_service(tmp_path)
    observer = CodexObserver(service, sessions_root=tmp_path / 'sessions', active_window_seconds=60)

    observer.sync()

    task = service.list_tasks()[0]
    assert task.control_mode == 'observed'
    assert task.status == 'done'
    assert task.source_metadata['runtime_status'] == 'ended'
    with sessions() as s:
        run = s.query(Run).one()
        assert run.status == 'ended'


def test_observed_projection_keeps_session_identity_but_uses_human_task_title(tmp_path):
    rollout = tmp_path / 'sessions/2026/10/14/rollout-demo-session-77.jsonl'
    write_rows(rollout, [
        {'timestamp':'2026-10-14T08:10:00Z','type':'session_meta','payload':{'id':'session-77','cwd':'/repo/taskfsm','source':'cli'}},
        {'timestamp':'2026-10-14T08:10:01Z','type':'event_msg','payload':{'type':'user_message','message':'分析 Observe Mode 状态误判并修复'}},
        {'timestamp':'2026-10-14T08:10:02Z','type':'event_msg','payload':{'type':'agent_message','message':'正在检查状态推断逻辑。'}},
    ])
    service, sessions = make_service(tmp_path)
    observer = CodexObserver(service, sessions_root=tmp_path / 'sessions', active_window_seconds=3600)

    observer.sync()

    task = service.list_tasks()[0]
    assert task.title == '分析 Observe Mode 状态误判并修复'
    assert task.external_id == 'session-77'
    assert task.source_metadata['session_id'] == 'session-77'
    assert task.source_metadata['workspace_name'] == 'taskfsm'
    assert task.source_metadata['task_intent'] == '分析 Observe Mode 状态误判并修复'
