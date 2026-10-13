from dataclasses import dataclass


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class TransitionContext:
    status: str
    dependencies_done: bool
    owns_active_lease: bool
    has_artifact: bool
    review_approved: bool


def apply_action(ctx: TransitionContext, action: str) -> str:
    if ctx.status == 'in_progress' and action == 'complete':
        raise TransitionError('进行中任务不能直接完成，必须先提交审查')

    if ctx.status == 'in_progress' and action == 'request_review':
        if not ctx.owns_active_lease:
            raise TransitionError('提交审查需要有效租约')
        if not ctx.has_artifact:
            raise TransitionError('提交审查前至少需要一个产物')
        if not ctx.dependencies_done:
            raise TransitionError('依赖任务尚未全部完成')
        return 'review'

    if ctx.status == 'review' and action == 'complete':
        if not ctx.review_approved:
            raise TransitionError('任务完成前需要审查批准')
        if not ctx.dependencies_done:
            raise TransitionError('依赖任务尚未全部完成')
        return 'done'

    if ctx.status == 'ready' and action == 'claim':
        if not ctx.dependencies_done:
            raise TransitionError('依赖任务尚未全部完成')
        return 'in_progress'

    if ctx.status in {'ready', 'in_progress', 'review'} and action == 'block':
        return 'blocked'

    if ctx.status == 'blocked' and action == 'unblock':
        if not ctx.dependencies_done:
            raise TransitionError('依赖任务尚未全部完成')
        return 'ready'

    simple = {
        ('backlog', 'triage'): 'todo',
        ('todo', 'mark_ready'): 'ready',
        ('review', 'request_changes'): 'in_progress',
        ('in_progress', 'release'): 'ready',
    }
    result = simple.get((ctx.status, action))
    if result:
        if result == 'ready' and not ctx.dependencies_done:
            raise TransitionError('依赖任务尚未全部完成')
        return result

    raise TransitionError(f'状态 {ctx.status} 不允许动作 {action}')
