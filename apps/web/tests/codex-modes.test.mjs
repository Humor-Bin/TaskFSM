import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('界面提供 Codex 自动/手动同步入口并区分两种模式', async () => {
  const html = await read('../index.html');
  const app = await read('../src/app.mjs');
  assert.match(html, /id="codexSync"/);
  assert.match(html, /Observed \+ Managed/);
  assert.match(app, /controlMode/);
  assert.match(app, /syncCodex/);
  assert.match(app, /Observed/);
  assert.match(app, /Managed/);
});

test('Observed 任务在前端不允许通过 TaskFSM 状态动作完成', async () => {
  const app = await read('../src/app.mjs');
  assert.match(app, /Observed 任务由外部 Agent 状态驱动/);
  assert.match(app, /Observed 任务不能由 TaskFSM 完成/);
});

test('运行视图明确区分 Agent Runtime 与 Managed FSM', async () => {
  const html = await read('../index.html');
  const app = await read('../src/app.mjs');
  assert.match(html, /Agent Runtime/);
  assert.match(html, /Managed FSM/);
  assert.match(app, /活跃 Session/);
  assert.match(app, /等待输入/);
  assert.match(app, /历史 Session/);
  assert.match(app, /managedSummary/);
  assert.match(app, /observedRuntimeSummary/);
});

test('Observed 详情优先展示人类可读任务、工作区、会话和原生计划', async () => {
  const app = await read('../src/app.mjs');
  for (const token of ['taskIntent', 'workspaceName', 'gitBranch', 'runtimeStatus', '原生执行计划', '当前任务', '工作区', 'Session']) {
    assert.match(app, new RegExp(token));
  }
  assert.doesNotMatch(app, /当前动作<\/dt><dd>\$\{escapeHtml\(task\.currentAction\|\|'—'\)\}/);
});

test('没有活跃 Session 时仍展示最近历史会话而不是空白画布', async () => {
  const app = await read('../src/app.mjs');
  assert.match(app, /最近会话/);
  assert.match(app, /recentObserved/);
  assert.match(app, /showingHistory/);
  assert.match(app, /最近历史会话/);
});
