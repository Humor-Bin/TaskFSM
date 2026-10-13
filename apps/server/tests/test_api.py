from fastapi.testclient import TestClient

from taskfsm.main import create_app


def test_full_agent_http_flow_and_dashboard():
    app = create_app('sqlite+pysqlite:///:memory:', testing=True)
    with TestClient(app) as client:
        agent = client.post('/api/agents/register', json={'name':'Nova','kind':'codex','capabilities':['python']}).json()
        headers={'Authorization':f"Bearer {agent['api_token']}"}
        dep = client.post('/api/tasks', json={'title':'准备数据','status':'done'}).json()
        task = client.post('/api/tasks', json={'title':'构建索引','status':'ready','required_capabilities':['python'],'dependency_ids':[dep['id']]}).json()
        available = client.get('/api/agent/tasks/available', params={'agent_id':agent['id']}, headers=headers)
        assert available.status_code == 200
        assert available.json()[0]['id'] == task['id']
        claim = client.post(f"/api/tasks/{task['id']}/claim", json={'agent_id':agent['id'],'lease_seconds':600}, headers=headers)
        assert claim.status_code == 200
        lease_id = claim.json()['lease']['id']
        assert claim.json()['task']['status'] == 'in_progress'
        assert client.post(f'/api/leases/{lease_id}/heartbeat', json={'agent_id':agent['id']}, headers=headers).status_code == 200
        assert client.post(f"/api/tasks/{task['id']}/progress", json={'agent_id':agent['id'],'progress':55,'current_action':'生成索引'}, headers=headers).status_code == 200
        assert client.post(f"/api/tasks/{task['id']}/artifacts", json={'agent_id':agent['id'],'type':'report','uri':'memory://report'}, headers=headers).status_code == 200
        assert client.post(f"/api/tasks/{task['id']}/request-review", json={'agent_id':agent['id']}, headers=headers).json()['status'] == 'review'
        assert client.post(f"/api/tasks/{task['id']}/reviews", json={'reviewer':'human:alice','decision':'approved','reason':'通过'}).status_code == 200
        assert client.post(f"/api/tasks/{task['id']}/complete", json={'actor':'human:alice'}).json()['status'] == 'done'
        dashboard = client.get('/api/dashboard').json()
        assert dashboard['summary']['done'] == 2
        assert any(item['name'] == 'Nova' for item in dashboard['agents'])
        assert any(event['event_type'] == 'task.completed' for event in dashboard['events'])


def test_domain_errors_become_409():
    app = create_app('sqlite+pysqlite:///:memory:', testing=True)
    with TestClient(app) as client:
        task = client.post('/api/tasks', json={'title':'不能直接完成','status':'in_progress'}).json()
        response = client.post(f"/api/tasks/{task['id']}/complete", json={'actor':'human:alice'})
        assert response.status_code == 409
        assert '不能直接完成' in response.json()['detail']


def test_health_endpoint():
    app = create_app('sqlite+pysqlite:///:memory:', testing=True)
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status':'ok'}


def test_agent_mutation_requires_matching_bearer_token():
    app = create_app('sqlite+pysqlite:///:memory:', testing=True)
    with TestClient(app) as client:
        agent = client.post('/api/agents/register', json={'name':'Nova','kind':'codex','capabilities':['python']}).json()
        task = client.post('/api/tasks', json={'title':'安全任务','status':'ready','required_capabilities':['python']}).json()
        assert client.post(f"/api/tasks/{task['id']}/claim", json={'agent_id':agent['id']}).status_code == 401
        assert client.post(f"/api/tasks/{task['id']}/claim", json={'agent_id':agent['id']}, headers={'Authorization':'Bearer wrong'}).status_code == 401


def test_web_console_is_served_at_root():
    app = create_app('sqlite+pysqlite:///:memory:', testing=True)
    with TestClient(app) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert 'TaskFSM' in response.text
