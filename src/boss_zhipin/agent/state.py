"""把数据库现状读成 ``DailyState``。

单独一个模块是为了让 ``planner`` 保持纯函数——测评可以直接构造 ``DailyState``
快照，不需要造数据库。这里是唯一碰 DB 的地方，且只用只读工具。
"""

from __future__ import annotations

from datetime import timedelta

from boss_zhipin.agent.planner import DailyState
from boss_zhipin.agent.tools import ToolRegistry
from boss_zhipin.domain.application_status import ApplicationStatus
from boss_zhipin.persistence.schema import utc_now

#: 投出去多少天没回应就算"超期"（蓝图第 4 节：投后 14 天无响应标 ghosted）
GHOST_AFTER_DAYS = 14


def collect_state(
    registry: ToolRegistry,
    *,
    daily_quota: int = 12,
    ghost_after_days: int = GHOST_AFTER_DAYS,
) -> DailyState:
    """只调注册表里的只读工具，不写任何东西。"""

    queue = registry.get("list_review_queue")(limit=100)
    applications = registry.get("list_applications")(limit=200)

    drafts_pending = 0
    for item in queue["items"]:
        draft = item.get("draft")
        if draft is not None and draft["reviewState"] == "pending":
            drafts_pending += 1

    needs_review_unscored = sum(
        1
        for item in queue["items"]
        if item["ruleMatch"]["state"] == "needs_review"
        and (item.get("evaluation") is None or item["evaluation"].get("score") is None)
    )

    counts = applications["countsByStatus"]
    approved_not_submitted = counts.get(ApplicationStatus.PREPARING.value, 0) + counts.get(
        ApplicationStatus.READY.value, 0
    )

    cutoff = utc_now() - timedelta(days=ghost_after_days)
    submitted_awaiting = 0
    stale_awaiting = 0
    for item in applications["items"]:
        if item["status"] != ApplicationStatus.SUBMITTED.value:
            continue
        if item["firstResponseAt"] is not None:
            continue
        submitted_awaiting += 1
        submitted_at = item["submittedAt"]
        if submitted_at is not None and _parse(submitted_at) < cutoff:
            stale_awaiting += 1

    used_today = counts.get(ApplicationStatus.SUBMITTED.value, 0)
    return DailyState(
        eligible=queue["totalEligible"],
        needs_review=queue["totalNeedsReview"],
        drafts_pending=drafts_pending,
        approved_not_submitted=approved_not_submitted,
        submitted_awaiting_response=submitted_awaiting,
        stale_awaiting_response=stale_awaiting,
        remaining_daily_quota=max(0, daily_quota - used_today),
        needs_review_unscored=needs_review_unscored,
    )


def _parse(value: str):
    from datetime import datetime

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        from datetime import timezone

        return parsed.replace(tzinfo=timezone.utc)
    return parsed
