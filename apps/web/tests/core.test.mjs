import test from 'node:test';
import assert from 'node:assert/strict';
import { canTransition, transitionTask, summarizeTasks, createEvent } from '../src/core.mjs';

const baseTasks = [
  { id: 'TASK-089', title: '准备检索数据', status: '已完成', dependencies: [] },
  { id: 'TASK-103', title: '构建知识库索引', status: '进行中', dependencies: ['TASK-089'] },
  { id: 'TASK-104', title: '设计检索策略', status: '待审查', dependencies: ['TASK-103'] },
  { id: 'TASK-107', title: '修复登录问题', status: '已阻塞', dependencies: [] }
];

test('进行中任务不能直接标记为已完成', () => {
  const result = canTransition(baseTasks[1], '已完成', baseTasks);
  assert.equal(result.allowed, false);
  assert.match(result.reason, /先提交审查/);
});

test('待审查任务在依赖未完成时不能完成', () => {
  const result = canTransition(baseTasks[2], '已完成', baseTasks);
  assert.equal(result.allowed, false);
  assert.match(result.reason, /依赖任务/);
});

test('进行中可以提交到待审查并且不修改原对象', () => {
  const result = transitionTask(baseTasks[1], '待审查', baseTasks);
  assert.equal(result.task.status, '待审查');
  assert.equal(baseTasks[1].status, '进行中');
  assert.equal(result.allowed, true);
});

test('状态统计返回关键流水线计数', () => {
  const summary = summarizeTasks(baseTasks);
  assert.equal(summary['进行中'], 1);
  assert.equal(summary['待审查'], 1);
  assert.equal(summary['已阻塞'], 1);
  assert.equal(summary['已完成'], 1);
});

test('事件记录包含操作者和原因', () => {
  const event = createEvent({ actor: 'Nova', actorType: 'agent', taskId: 'TASK-103', text: '提交审查', severity: 'info' });
  assert.equal(event.actor, 'Nova');
  assert.equal(event.taskId, 'TASK-103');
  assert.equal(event.text, '提交审查');
  assert.ok(event.id);
  assert.ok(event.time);
});
