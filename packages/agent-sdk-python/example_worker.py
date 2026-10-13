"""最小 Agent 示例：注册、领取一个匹配任务、上报进度、提交产物并申请审查。"""
import os
from taskfsm_agent import TaskFSMClient

BASE_URL = os.getenv('TASKFSM_URL', 'http://127.0.0.1:8000')

client = TaskFSMClient(BASE_URL)
registration = client.register('Example-Coder', 'custom', ['python', 'testing'])
agent_id = registration['id']
print('registered:', agent_id)

tasks = client.available_tasks(agent_id)
if not tasks:
    print('没有可领取任务')
    raise SystemExit(0)

claim = client.claim(tasks[0]['id'], agent_id)
lease_id = claim['lease']['id']
task_id = claim['task']['id']
client.progress(task_id, agent_id, 25, '开始分析任务')
client.lease_heartbeat(lease_id, agent_id)

# 在这里调用你自己的 Codex / Claude Code / 自研 Agent 执行逻辑。
client.progress(task_id, agent_id, 90, '执行完成，准备提交产物')
client.submit_artifact(task_id, agent_id, 'report', 'file://result.md', {'source': 'example_worker'})
client.request_review(task_id, agent_id)
print('submitted for review:', task_id)
