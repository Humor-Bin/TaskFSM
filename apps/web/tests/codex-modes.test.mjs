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
