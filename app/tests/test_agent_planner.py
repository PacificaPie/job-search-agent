"""当日操盘 planner 测试。

它是未来 LLM planner 的对照组，所以这里的断言其实是在钉「什么叫合理的今日排程」。
"""

from boss_zhipin.agent.planner import (
    BACKLOG_THRESHOLD,
    PENDING_DRAFT_CEILING,
    ActionKind,
    DailyState,
    plan_today,
)


def _kinds(state: DailyState) -> list[ActionKind]:
    return [action.kind for action in plan_today(state).actions]


def test_empty_queue_means_capture():
    """池子空、额度还在 → 去抓，而不是休息。"""
    assert _kinds(DailyState(remaining_daily_quota=12)) == [ActionKind.CAPTURE]


def test_rest_when_quota_is_gone_and_nothing_is_pending():
    """额度用完又没有待办 → 明确说「今天不用动」，而不是硬凑一个抓取动作。

    抓取是最贵的动作，今天抓了也动不了，不如明天再抓。
    """
    assert _kinds(DailyState(remaining_daily_quota=0)) == [ActionKind.REST]


def test_stale_submissions_are_marked_before_anything_else():
    """超期未回应会让回调率虚高，必须最先处理。"""
    state = DailyState(
        eligible=5,
        needs_review=30,
        submitted_awaiting_response=4,
        stale_awaiting_response=2,
    )
    kinds = _kinds(state)
    assert kinds[0] is ActionKind.MARK_GHOSTED
    assert ActionKind.FOLLOW_UP in kinds  # 剩下 2 条没超期的仍要跟进


def test_approved_but_not_submitted_ranks_above_generating_more():
    """离产出最近的一格优先：已批准的先投出去，别急着生成新草稿。"""
    state = DailyState(eligible=5, approved_not_submitted=3)
    kinds = _kinds(state)
    assert kinds.index(ActionKind.HUMAN_APPROVE) < kinds.index(ActionKind.DRAFT)


def test_full_review_desk_stops_draft_generation():
    """审核台塞满时不再生成——避免把成本花在最不缺的地方。"""
    state = DailyState(eligible=20, drafts_pending=PENDING_DRAFT_CEILING)
    kinds = _kinds(state)
    assert ActionKind.DRAFT not in kinds
    assert ActionKind.HUMAN_APPROVE in kinds


def test_draft_count_respects_quota_and_desk_headroom():
    plan = plan_today(DailyState(eligible=20, remaining_daily_quota=3, drafts_pending=0))
    draft = next(a for a in plan.actions if a.kind is ActionKind.DRAFT)
    assert draft.count == 3

    plan = plan_today(DailyState(eligible=20, remaining_daily_quota=12, drafts_pending=6))
    draft = next(a for a in plan.actions if a.kind is ActionKind.DRAFT)
    assert draft.count == PENDING_DRAFT_CEILING - 6


def test_no_drafting_when_quota_is_used_up():
    kinds = _kinds(DailyState(eligible=5, remaining_daily_quota=0))
    assert ActionKind.DRAFT not in kinds


def test_backlog_triggers_scoring_before_triage():
    """积压时先打分排序，人工才不用从头翻 45 条。"""
    state = DailyState(needs_review=BACKLOG_THRESHOLD, needs_review_unscored=BACKLOG_THRESHOLD)
    kinds = _kinds(state)
    assert kinds.index(ActionKind.SCORE_NEEDS_REVIEW) < kinds.index(
        ActionKind.TRIAGE_NEEDS_REVIEW
    )

    # 已经全部打过分就不用再打
    scored = DailyState(needs_review=BACKLOG_THRESHOLD, needs_review_unscored=0)
    assert ActionKind.SCORE_NEEDS_REVIEW not in _kinds(scored)


def test_small_needs_review_is_plain_triage():
    kinds = _kinds(DailyState(needs_review=2, eligible=5))
    assert ActionKind.TRIAGE_NEEDS_REVIEW in kinds
    assert ActionKind.SCORE_NEEDS_REVIEW not in kinds


def test_capture_only_when_pipeline_is_thin():
    assert ActionKind.CAPTURE in _kinds(DailyState(eligible=1, needs_review=1))
    assert ActionKind.CAPTURE not in _kinds(DailyState(eligible=1, needs_review=40))


def test_plan_never_proposes_sending():
    """红线：planner 的动作词表里根本没有"发送"。"""
    every_kind = {kind for kind in ActionKind}
    assert not [k for k in every_kind if any(w in k.value for w in ("send", "submit", "apply"))]


def test_plan_is_pure_and_reproducible():
    state = DailyState(eligible=5, needs_review=44, needs_review_unscored=44)
    assert plan_today(state).as_dict() == plan_today(state).as_dict()
