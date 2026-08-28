"""``reachout-plan``：早上一条命令看今天该干什么。

只读。它不会抓岗位、不会生成草稿、更不会发送——只把当前状态和建议动作打出来，
干活还是由本人决定跑哪个命令。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from dotenv import load_dotenv

from boss_zhipin.agent.planner import plan_today
from boss_zhipin.agent.state import GHOST_AFTER_DAYS, collect_state
from boss_zhipin.agent.tools import build_default_registry
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import ProfilePreferenceRepository, ProfileRepository

_KIND_LABEL = {
    "capture": "抓取",
    "triage": "人工过审",
    "score": "打分排序",
    "draft": "生成草稿",
    "human_approve": "本人操作",
    "follow_up": "跟进",
    "mark_ghosted": "标记已读不回",
    "rest": "休息",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reachout-plan",
        description="读本地数据库现状，给出今日建议动作清单（只读，不会发送任何消息）。",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是人读格式")
    parser.add_argument(
        "--ghost-after-days",
        type=int,
        default=GHOST_AFTER_DAYS,
        help=f"投递后多少天无回应算超期，默认 {GHOST_AFTER_DAYS}",
    )
    return parser


def build_report(database, *, ghost_after_days: int = GHOST_AFTER_DAYS) -> dict:
    with database.session() as session:
        profile = ProfileRepository(session).get_active()
        preference = (
            ProfilePreferenceRepository(session).get(profile.id) if profile is not None else None
        )
        daily_quota = preference.daily_outreach_limit if preference is not None else 12

    registry = build_default_registry(database)
    state = collect_state(registry, daily_quota=daily_quota, ghost_after_days=ghost_after_days)
    plan = plan_today(state)
    return {
        "state": {
            "eligible": state.eligible,
            "needsReview": state.needs_review,
            "draftsPending": state.drafts_pending,
            "approvedNotSubmitted": state.approved_not_submitted,
            "submittedAwaitingResponse": state.submitted_awaiting_response,
            "staleAwaitingResponse": state.stale_awaiting_response,
            "remainingDailyQuota": state.remaining_daily_quota,
            "needsReviewUnscored": state.needs_review_unscored,
        },
        "actions": plan.as_dict()["actions"],
        "readonlyTools": list(registry.readonly_names()),
    }


def render(report: dict) -> str:
    state = report["state"]
    lines = [
        "今日操盘建议（只读，不会发送任何消息）",
        "",
        f"  当前状态：eligible {state['eligible']} · needs_review {state['needsReview']}"
        f"（未打分 {state['needsReviewUnscored']}） · 待批草稿 {state['draftsPending']}",
        f"            已批未投 {state['approvedNotSubmitted']} · 已投等回应"
        f" {state['submittedAwaitingResponse']}（超期 {state['staleAwaitingResponse']}）"
        f" · 今日剩余额度 {state['remainingDailyQuota']}",
        "",
        "  建议动作：",
    ]
    for index, action in enumerate(report["actions"], start=1):
        label = _KIND_LABEL.get(action["kind"], action["kind"])
        count = f"（{action['count']} 条）" if action["count"] is not None else ""
        lines.append(f"    {index}. [{label}]{count} {action['reason']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    database = Database()
    pending = database.pending_migrations()
    if pending:
        database.close()
        print(
            "数据库还有未应用的迁移："
            + "、".join(str(v) for v in pending)
            + "。本命令是只读的，不会替你改库结构——先跑一次 boss-zhipin-daily 或"
            " boss-zhipin-capture 让它迁移，再回来看今日计划。"
        )
        return 1
    try:
        report = build_report(database, ghost_after_days=args.ghost_after_days)
    finally:
        database.close()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
