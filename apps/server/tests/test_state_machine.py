import pytest

from taskfsm.domain.state_machine import TransitionContext, TransitionError, apply_action


def ctx(**overrides):
    base = dict(
        status='in_progress',
        dependencies_done=True,
        owns_active_lease=True,
        has_artifact=True,
        review_approved=False,
    )
    base.update(overrides)
    return TransitionContext(**base)


def test_in_progress_cannot_complete_directly():
    with pytest.raises(TransitionError, match='不能直接完成'):
        apply_action(ctx(), 'complete')


def test_request_review_requires_active_lease_and_artifact():
    with pytest.raises(TransitionError, match='有效租约'):
        apply_action(ctx(owns_active_lease=False), 'request_review')
    with pytest.raises(TransitionError, match='产物'):
        apply_action(ctx(has_artifact=False), 'request_review')
    assert apply_action(ctx(), 'request_review') == 'review'


def test_review_completion_requires_approval_and_dependencies():
    review_ctx = ctx(status='review', owns_active_lease=False, review_approved=False)
    with pytest.raises(TransitionError, match='审查批准'):
        apply_action(review_ctx, 'complete')
    with pytest.raises(TransitionError, match='依赖'):
        apply_action(ctx(status='review', owns_active_lease=False, review_approved=True, dependencies_done=False), 'complete')
    assert apply_action(ctx(status='review', owns_active_lease=False, review_approved=True), 'complete') == 'done'


def test_ready_claim_requires_dependencies():
    with pytest.raises(TransitionError, match='依赖'):
        apply_action(ctx(status='ready', dependencies_done=False, owns_active_lease=False, has_artifact=False), 'claim')
    assert apply_action(ctx(status='ready', dependencies_done=True, owns_active_lease=False, has_artifact=False), 'claim') == 'in_progress'


def test_block_and_unblock_paths():
    assert apply_action(ctx(), 'block') == 'blocked'
    assert apply_action(ctx(status='blocked', owns_active_lease=False, has_artifact=False), 'unblock') == 'ready'
