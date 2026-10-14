from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Any

from taskfsm.domain.service import DomainError, TaskFSMService


logger = logging.getLogger(__name__)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _clean_plan(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r'^[-*]\s+', '', line)
        line = re.sub(r'^\d+[.)]\s*', '', line)
        line = re.sub(r'^\[[ xX]\]\s*', '', line)
        if line:
            out.append(line)
    return out


def _event_message(payload: dict[str, Any]) -> str:
    for key in ('message', 'text', 'summary', 'name'):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    item = payload.get('item')
    if isinstance(item, dict):
        for key in ('text', 'message', 'name', 'type'):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ''


@dataclass
class CodexSessionSnapshot:
    session_id: str
    path: str
    cwd: str
    source: str
    title: str
    current_action: str
    status: str
    plan: list[str]
    last_event_at: datetime | None
    metadata: dict[str, Any]


class CodexRolloutParser:
    """Parse the stable, user-visible subset of Codex rollout JSONL.

    Unknown rows are intentionally ignored. This keeps TaskFSM tolerant of
    Codex schema growth while preserving source JSON as metadata/events.
    """

    def parse(self, path: str | Path) -> CodexSessionSnapshot:
        path = Path(path)
        session_id = path.stem.split('-')[-1]
        cwd = ''
        source = 'cli'
        title = ''
        current_action = ''
        plan: list[str] = []
        last_event_at: datetime | None = None
        waiting = False
        metadata: dict[str, Any] = {'rollout_path': str(path)}

        with path.open('r', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(row.get('timestamp'))
                if ts and (last_event_at is None or ts > last_event_at):
                    last_event_at = ts
                row_type = row.get('type')
                payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}

                if row_type == 'session_meta':
                    session_id = str(payload.get('id') or session_id)
                    cwd = str(payload.get('cwd') or cwd)
                    source = str(payload.get('source') or source)
                    metadata.update({k: v for k, v in payload.items() if k not in {'id', 'cwd'}})
                    continue

                if row_type != 'event_msg':
                    continue

                payload_type = payload.get('type')
                if payload_type == 'user_message':
                    message = str(payload.get('message') or '').strip()
                    if message and not title:
                        title = message.splitlines()[0][:300]
                    waiting = False
                    continue
                if payload_type == 'agent_message':
                    message = str(payload.get('message') or '').strip()
                    if message:
                        current_action = message[:300]
                    continue
                if payload_type in {'request_user_input', 'user_input_requested'}:
                    waiting = True
                    current_action = '等待用户输入'
                    continue
                item = payload.get('item')
                if payload_type == 'item_completed' and isinstance(item, dict) and str(item.get('type')).lower() == 'plan':
                    plan = _clean_plan(str(item.get('text') or ''))
                    continue
                message = _event_message(payload)
                if message:
                    current_action = message[:300]

        if not title:
            title = f'Codex Session {session_id[:12]}'
        if not current_action:
            current_action = '已发现 Codex 会话'
        status = 'waiting' if waiting else 'running'
        return CodexSessionSnapshot(
            session_id=session_id,
            path=str(path),
            cwd=cwd,
            source=source,
            title=title,
            current_action=current_action,
            status=status,
            plan=plan,
            last_event_at=last_event_at,
            metadata=metadata,
        )


class CodexObserver:
    def __init__(self, service: TaskFSMService, sessions_root: str | Path | None = None):
        self.service = service
        explicit_root = sessions_root is not None
        if sessions_root is None:
            codex_home = Path(os.getenv('CODEX_HOME', '~/.codex')).expanduser()
            sessions_root = codex_home / 'sessions'
        self.sessions_root = Path(sessions_root).expanduser()
        self.parser = CodexRolloutParser()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if not explicit_root and os.getenv('TASKFSM_CODEX_AUTO_SYNC', '1') == '1':
            self.start_background(float(os.getenv('TASKFSM_CODEX_SYNC_INTERVAL', '5')))

    def discover(self, limit: int = 200) -> list[Path]:
        if not self.sessions_root.exists():
            return []
        files = sorted(
            self.sessions_root.glob('*/*/*/rollout-*.jsonl'),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files[: max(1, min(limit, 1000))]

    def sync(self, limit: int = 200) -> dict[str, int]:
        files = self.discover(limit)
        imported = 0
        for path in files:
            try:
                snapshot = self.parser.parse(path)
                self.service.upsert_observed_codex_session(snapshot)
                imported += 1
            except (OSError, ValueError):
                continue
        return {'discovered': len(files), 'synced': imported}

    def start_background(self, interval_seconds: float = 5.0):
        if self._thread and self._thread.is_alive():
            return
        interval_seconds = max(1.0, float(interval_seconds))
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.sync()
                except Exception:
                    logger.exception('Codex observer background sync failed')
                self._stop.wait(interval_seconds)

        self._thread = threading.Thread(target=loop, name='taskfsm-codex-observer', daemon=True)
        self._thread.start()

    def stop_background(self):
        self._stop.set()


class CodexRuntimeManager:
    """Runs managed local Codex processes without making CLI output authoritative.

    Process JSONL is observability only. Task state transitions continue to go
    through TaskFSM actions/guards (typically via the TaskFSM MCP tools).
    """

    def __init__(self, service: TaskFSMService, command: str = 'codex'):
        self.service = service
        self.command = command
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def active_run_ids(self) -> list[str]:
        with self._lock:
            return [run_id for run_id, process in self._processes.items() if process.poll() is None]

    def start(self, task_id: str, workspace: str, prompt: str | None = None, lease_seconds: int = 1800):
        if os.getenv('TASKFSM_CODEX_MANAGED', '0') != '1':
            raise DomainError('Managed Codex 未启用，请设置 TASKFSM_CODEX_MANAGED=1')
        binary = shutil.which(self.command)
        if not binary:
            raise DomainError('未找到 codex CLI')
        workspace_path = Path(workspace).expanduser().resolve()
        if not workspace_path.exists() or not workspace_path.is_dir():
            raise DomainError('工作目录不存在')

        claim = self.service.claim_task_for_codex(task_id, workspace=str(workspace_path), lease_seconds=lease_seconds)
        task = claim.task
        default_prompt = (
            f'你正在执行 TaskFSM 任务 {task.id}: {task.title}\n\n'
            f'{task.description}\n\n'
            '请使用 TaskFSM MCP 工具读取当前任务、上报进度、提交产物并请求审查。'
            'Codex 自己的 plan/todo 仅用于执行细节，不能直接改变 TaskFSM 状态。'
        )
        env = os.environ.copy()
        env.update({
            'TASKFSM_TASK_ID': task.id,
            'TASKFSM_RUN_ID': claim.run.id,
            'TASKFSM_AGENT_ID': claim.agent_id,
            'TASKFSM_AGENT_TOKEN': claim.agent_token,
            'TASKFSM_LEASE_ID': claim.lease.id,
        })
        command = [binary, 'exec', '--json', '-C', str(workspace_path), prompt or default_prompt]
        try:
            process = subprocess.Popen(
                command,
                cwd=str(workspace_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.service.fail_managed_run(claim.run.id, f'启动 Codex 失败: {exc}')
            raise DomainError(f'启动 Codex 失败: {exc}') from exc

        self.service.attach_managed_process(claim.run.id, process.pid)
        with self._lock:
            self._processes[claim.run.id] = process
        thread = threading.Thread(target=self._consume, args=(claim.run.id, process), daemon=True)
        thread.start()
        return claim

    def _consume(self, run_id: str, process: subprocess.Popen[str]):
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {'type': 'stdout', 'message': line}
            self.service.ingest_codex_runtime_event(run_id, event)
        exit_code = process.wait()
        self.service.finish_managed_codex_run(run_id, exit_code)
        with self._lock:
            self._processes.pop(run_id, None)

    def stop(self, run_id: str) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
        if not process or process.poll() is not None:
            return False
        process.terminate()
        return True
