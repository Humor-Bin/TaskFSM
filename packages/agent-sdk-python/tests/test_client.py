import json
import httpx

from taskfsm_agent.client import TaskFSMClient


def test_sdk_builds_agent_runtime_requests():
    seen=[]
    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content or b'{}')))
        if request.url.path == '/api/agents/register':
            return httpx.Response(200, json={'id':'agent_1','api_token':'tok','name':'Nova'})
        if request.url.path == '/api/agent/tasks/available':
            return httpx.Response(200, json=[{'id':'task_1'}])
        if request.url.path.endswith('/claim'):
            return httpx.Response(200, json={'task':{'id':'task_1'},'lease':{'id':'lease_1'},'run':{'id':'run_1'}})
        return httpx.Response(200, json={'ok':True})

    http = httpx.Client(base_url='http://taskfsm.local', transport=httpx.MockTransport(handler))
    client = TaskFSMClient('http://taskfsm.local', http_client=http)
    reg = client.register('Nova','codex',['python'])
    assert reg['id']=='agent_1'
    assert client.available_tasks('agent_1')[0]['id']=='task_1'
    claim = client.claim('task_1','agent_1',300)
    client.lease_heartbeat(claim['lease']['id'],'agent_1')
    client.progress('task_1','agent_1',50,'编码中')
    client.submit_artifact('task_1','agent_1','git_commit','git://abc')
    client.request_review('task_1','agent_1')
    paths=[item[1] for item in seen]
    assert '/api/agents/register' in paths
    assert '/api/tasks/task_1/request-review' in paths
