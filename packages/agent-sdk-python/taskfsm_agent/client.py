from __future__ import annotations
import httpx


class TaskFSMClient:
    def __init__(self, base_url: str, token: str | None = None, http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip('/')
        self._owns_client = http_client is None
        headers = {'Authorization': f'Bearer {token}'} if token else None
        self.http = http_client or httpx.Client(base_url=self.base_url, headers=headers, timeout=20.0)
        self.token = token

    def close(self):
        if self._owns_client:
            self.http.close()

    def _post(self, path: str, payload: dict):
        response = self.http.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def register(self, name: str, kind: str = 'generic', capabilities: list[str] | None = None):
        data = self._post('/api/agents/register', {'name': name, 'kind': kind, 'capabilities': capabilities or []})
        if data.get('api_token'):
            self.token = data['api_token']
            self.http.headers['Authorization'] = f"Bearer {self.token}"
        return data

    def heartbeat(self, agent_id: str):
        return self._post(f'/api/agents/{agent_id}/heartbeat', {})

    def available_tasks(self, agent_id: str):
        response = self.http.get('/api/agent/tasks/available', params={'agent_id': agent_id})
        response.raise_for_status()
        return response.json()

    def claim(self, task_id: str, agent_id: str, lease_seconds: int = 600):
        return self._post(f'/api/tasks/{task_id}/claim', {'agent_id': agent_id, 'lease_seconds': lease_seconds})

    def lease_heartbeat(self, lease_id: str, agent_id: str, extend_seconds: int = 600):
        return self._post(f'/api/leases/{lease_id}/heartbeat', {'agent_id': agent_id, 'extend_seconds': extend_seconds})

    def progress(self, task_id: str, agent_id: str, progress: int, current_action: str):
        return self._post(f'/api/tasks/{task_id}/progress', {'agent_id': agent_id, 'progress': progress, 'current_action': current_action})

    def submit_artifact(self, task_id: str, agent_id: str, artifact_type: str, uri: str, metadata: dict | None = None):
        return self._post(f'/api/tasks/{task_id}/artifacts', {'agent_id': agent_id, 'type': artifact_type, 'uri': uri, 'metadata': metadata or {}})

    def request_review(self, task_id: str, agent_id: str):
        return self._post(f'/api/tasks/{task_id}/request-review', {'agent_id': agent_id})
