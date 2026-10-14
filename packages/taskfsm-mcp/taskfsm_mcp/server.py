from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP('TaskFSM')


def _env(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'缺少环境变量 {name}')
    return value


def _base_url() -> str:
    return os.getenv('TASKFSM_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')


def _headers() -> dict[str, str]:
    return {'Authorization': f"Bearer {_env('TASKFSM_AGENT_TOKEN')}"}


def _request(method: str, path: str, **kwargs) -> Any:
    with httpx.Client(base_url=_base_url(), timeout=20.0) as client:
        response = client.request(method, path, **kwargs)
    if response.is_error:
        try:
            detail = response.json().get('detail')
        except Exception:
            detail = response.text
        raise RuntimeError(f'TaskFSM {response.status_code}: {detail}')
    return response.json()


@mcp.tool()
def get_current_task() -> dict:
    """读取本次 Codex Run 被分配的 TaskFSM 任务。"""
    return _request('GET', f"/api/tasks/{_env('TASKFSM_TASK_ID')}")


@mcp.tool()
def heartbeat(extend_seconds: int = 600) -> dict:
    """刷新当前 TaskFSM Lease，表示 Agent 仍在健康执行。"""
    return _request(
        'POST', f"/api/leases/{_env('TASKFSM_LEASE_ID')}/heartbeat",
        headers=_headers(),
        json={'agent_id': _env('TASKFSM_AGENT_ID'), 'extend_seconds': extend_seconds},
    )


@mcp.tool()
def report_progress(progress: int, current_action: str) -> dict:
    """上报可观测进度和当前动作；不会绕过 TaskFSM 状态机。"""
    progress = max(0, min(100, int(progress)))
    return _request(
        'POST', f"/api/tasks/{_env('TASKFSM_TASK_ID')}/progress",
        headers=_headers(),
        json={'agent_id': _env('TASKFSM_AGENT_ID'), 'progress': progress, 'current_action': current_action},
    )


@mcp.tool()
def submit_artifact(artifact_type: str, uri: str, metadata: dict | None = None) -> dict:
    """提交代码提交、PR、文件、报告等任务产物。"""
    return _request(
        'POST', f"/api/tasks/{_env('TASKFSM_TASK_ID')}/artifacts",
        headers=_headers(),
        json={'agent_id': _env('TASKFSM_AGENT_ID'), 'type': artifact_type, 'uri': uri, 'metadata': metadata or {}},
    )


@mcp.tool()
def request_review() -> dict:
    """任务产物准备完毕后请求进入 Review；由服务端 Guard 决定是否允许。"""
    return _request(
        'POST', f"/api/tasks/{_env('TASKFSM_TASK_ID')}/request-review",
        headers=_headers(),
        json={'agent_id': _env('TASKFSM_AGENT_ID')},
    )


def main():
    mcp.run()


if __name__ == '__main__':
    main()
