import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');

test('页面包含运行控制台的关键区域', async () => {
  const html = await read('../index.html');
  for (const id of ['summaryGrid', 'pipeline', 'topology', 'taskDetail', 'runningTasks', 'eventFeed', 'toast']) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /运行视图/);
  assert.match(html, /TaskFSM/);
});

test('交互脚本暴露任务选择和状态迁移操作', async () => {
  const app = await read('../src/app.mjs');
  for (const token of ['selectTask', 'submitReview', 'markComplete', 'togglePause', 'renderTopology', 'showToast']) {
    assert.match(app, new RegExp(token));
  }
});

test('界面样式包含运行流动和心跳状态动效', async () => {
  const css = await read('../src/styles.css');
  assert.match(css, /@keyframes\s+flow/);
  assert.match(css, /@keyframes\s+pulse/);
  assert.match(css, /\.edge\.active/);
  assert.match(css, /\.actor-agent/);
  assert.match(css, /\.actor-human/);
});
