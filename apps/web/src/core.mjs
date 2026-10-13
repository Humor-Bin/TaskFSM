const PIPELINE = ['任务池', '待办', '就绪', '进行中', '待审查', '已阻塞', '已完成'];

export function summarizeTasks(tasks) {
  const summary = Object.fromEntries(PIPELINE.map((status) => [status, 0]));
  for (const task of tasks) {
    if (summary[task.status] === undefined) summary[task.status] = 0;
    summary[task.status] += 1;
  }
  return summary;
}

export function canTransition(task, nextStatus, tasks) {
  if (!task) return { allowed: false, reason: '未找到任务' };
  if (task.status === nextStatus) return { allowed: true, reason: '状态未变化' };

  if (task.status === '进行中' && nextStatus === '已完成') {
    return { allowed: false, reason: '进行中任务必须先提交审查，不能直接标记完成。' };
  }

  if (task.status === '进行中' && nextStatus === '待审查') {
    return { allowed: true, reason: '允许提交审查' };
  }

  if (task.status === '待审查' && nextStatus === '已完成') {
    const unfinished = (task.dependencies || []).filter((id) => {
      const dependency = tasks.find((item) => item.id === id);
      return !dependency || dependency.status !== '已完成';
    });
    if (unfinished.length) {
      return { allowed: false, reason: `依赖任务 ${unfinished.join('、')} 尚未完成。` };
    }
    return { allowed: true, reason: '审查与依赖检查通过' };
  }

  const allowedPairs = new Set([
    '任务池>待办', '待办>就绪', '就绪>进行中', '已阻塞>进行中', '待审查>进行中'
  ]);
  if (allowedPairs.has(`${task.status}>${nextStatus}`)) {
    return { allowed: true, reason: '状态机允许此迁移' };
  }

  return { allowed: false, reason: `状态机不允许从“${task.status}”迁移到“${nextStatus}”。` };
}

export function transitionTask(task, nextStatus, tasks) {
  const guard = canTransition(task, nextStatus, tasks);
  if (!guard.allowed) return { ...guard, task };
  return {
    allowed: true,
    reason: guard.reason,
    task: { ...task, status: nextStatus }
  };
}

export function createEvent({ actor, actorType, taskId, text, severity = 'info', at = new Date() }) {
  const time = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(at);
  return {
    id: `evt_${at.getTime()}_${Math.random().toString(36).slice(2, 7)}`,
    time,
    actor,
    actorType,
    taskId,
    severity,
    text
  };
}
