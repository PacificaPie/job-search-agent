"""当日操盘：读状态 → 排出今天该干什么。

这是 agent 决策层的**确定性对照组**。它故意写得很朴素（一堆显式规则），
因为它的作用不是"聪明"，而是给未来的 LLM planner 一条必须跨过的及格线：
LLM 版本要在 L4 决策测评上不劣于它，才允许接管（见 docs/agent化改造方案.md §5）。

设计约束：
- ``plan_today`` 是**纯函数**：吃一个 ``DailyState``，吐一个 ``DailyPlan``，不碰 DB、
  不看时钟。这样测评可以直接构造状态快照，不需要造一个数据库。
- 行动里永远不会出现"发送"。最重就是"把 N 条草稿放到审核台等人批"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActionKind(StrEnum):
    CAPTURE = "capture"                    # 去抓新岗位
    TRIAGE_NEEDS_REVIEW = "triage"         # 清 needs_review 积压
    SCORE_NEEDS_REVIEW = "score"           # 给 needs_review 跑打分做二次排序
    DRAFT = "draft"                        # 给 eligible 岗位生成草稿
    HUMAN_APPROVE = "human_approve"        # 等人批准（人的动作，不是系统的）
    FOLLOW_UP = "follow_up"                # 跟进已投递但久无回音的
    MARK_GHOSTED = "mark_ghosted"          # 超期未回复的标 ghosted
    REST = "rest"                          # 今天没什么可做


@dataclass(frozen=True, slots=True)
class DailyState:
    """决策所需的全部输入。字段全部来自只读工具，没有隐藏依赖。"""

    eligible: int = 0
    needs_review: int = 0
    #: eligible 里已经有草稿、正等人批的条数
    drafts_pending: int = 0
    #: 已批准但还没标记为已投递的条数
    approved_not_submitted: int = 0
    #: 已投递且还没有任何回应的条数
    submitted_awaiting_response: int = 0
    #: 已投递超过 ghost 阈值天数仍无回应的条数
    stale_awaiting_response: int = 0
    #: 今日还剩多少触达额度
    remaining_daily_quota: int = 12
    #: 队列里还没打过分的 needs_review 条数
    needs_review_unscored: int = 0


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    reason: str
    #: 建议处理的条数；None 表示不涉及数量
    count: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "reason": self.reason, "count": self.count}


@dataclass(frozen=True, slots=True)
class DailyPlan:
    actions: tuple[Action, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {"actions": [action.as_dict() for action in self.actions]}


#: needs_review 超过这个数就认为"积压"，优先清而不是继续抓新的
BACKLOG_THRESHOLD = 20
#: 审核台里等批的草稿超过这个数就别再生成了，先让人消化
PENDING_DRAFT_CEILING = 8
#: 岗位池低于这个数才值得去抓新的
THIN_PIPELINE_THRESHOLD = 3


def plan_today(state: DailyState) -> DailyPlan:
    """排出今天的行动清单，按优先级从高到低。

    优先级次序背后的道理：**先把已经花过成本的东西推到下一格，再去制造新的库存。**
    抓一堆新岗位却让审核台积压 44 条，等于把成本花在了最不缺的地方。
    """

    actions: list[Action] = []

    # 1. 超期未回复的先标掉——它们伪装成"在流程里"，会让回调率虚高
    if state.stale_awaiting_response > 0:
        actions.append(
            Action(
                ActionKind.MARK_GHOSTED,
                f"{state.stale_awaiting_response} 条投递超期无回应，标记 ghosted 免得混在 submitted 里看不见",
                state.stale_awaiting_response,
            )
        )

    # 2. 已批准但没投出去的——离产出最近的一格，成本已经花完了
    if state.approved_not_submitted > 0:
        actions.append(
            Action(
                ActionKind.HUMAN_APPROVE,
                f"{state.approved_not_submitted} 条已批准还没投出去，本人手动发送后把状态推到 submitted",
                state.approved_not_submitted,
            )
        )

    # 3. 审核台积压优先于生成新草稿
    if state.drafts_pending >= PENDING_DRAFT_CEILING:
        actions.append(
            Action(
                ActionKind.HUMAN_APPROVE,
                f"审核台已有 {state.drafts_pending} 条待批草稿，先消化再生成新的",
                state.drafts_pending,
            )
        )
    elif state.eligible > 0 and state.remaining_daily_quota > 0:
        count = min(state.eligible, state.remaining_daily_quota, PENDING_DRAFT_CEILING - state.drafts_pending)
        if count > 0:
            actions.append(
                Action(ActionKind.DRAFT, f"{state.eligible} 个 eligible 岗位待生成草稿", count)
            )

    # 4. needs_review 积压：先打分排序，再让人按分从高往低看
    if state.needs_review >= BACKLOG_THRESHOLD:
        if state.needs_review_unscored > 0:
            actions.append(
                Action(
                    ActionKind.SCORE_NEEDS_REVIEW,
                    f"{state.needs_review} 条 needs_review 积压，其中 {state.needs_review_unscored} 条还没打分；"
                    "先打分排序，人工审核才不用从头翻",
                    state.needs_review_unscored,
                )
            )
        actions.append(
            Action(
                ActionKind.TRIAGE_NEEDS_REVIEW,
                f"needs_review 积压 {state.needs_review} 条（阈值 {BACKLOG_THRESHOLD}），按分从高往低人工过一遍",
                state.needs_review,
            )
        )
    elif state.needs_review > 0:
        actions.append(
            Action(
                ActionKind.TRIAGE_NEEDS_REVIEW,
                f"{state.needs_review} 条 needs_review 待人工判断",
                state.needs_review,
            )
        )

    # 5. 池子确实薄了才去抓新的——抓取是最贵的动作（开浏览器、有风控成本），
    #    而且今日额度已经用完时抓了也动不了，不如明天再抓。
    pipeline = state.eligible + state.needs_review
    if pipeline <= THIN_PIPELINE_THRESHOLD and state.remaining_daily_quota > 0:
        actions.append(
            Action(
                ActionKind.CAPTURE,
                f"可跟进岗位仅 {pipeline} 个，跑一轮定向抓取补充池子",
            )
        )

    # 6. 跟进：已投递、还在等、也没超期
    if state.submitted_awaiting_response > state.stale_awaiting_response:
        waiting = state.submitted_awaiting_response - state.stale_awaiting_response
        actions.append(
            Action(ActionKind.FOLLOW_UP, f"{waiting} 条投递在等回应，检查是否有该跟进的", waiting)
        )

    if not actions:
        actions.append(Action(ActionKind.REST, "队列干净、没有待批也没有待跟进，今天不用动"))

    return DailyPlan(tuple(actions))
