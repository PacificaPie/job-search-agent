"""Daily personal workflow: targeted capture and local screening, never send."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence

import nodriver as uc
from dotenv import load_dotenv

from boss_zhipin.application.capture_service import CaptureService
from boss_zhipin.application.review_service import ReviewService
from boss_zhipin.domain.campaign import CHINA_CAMPUS_CAMPAIGN
from boss_zhipin.domain.job_filter import JobFilterConfig, evaluate_job_rules
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    JobCampaignMatchRepository,
    JobRepository,
    ProfilePreferenceRepository,
    ProfileRepository,
    SearchCampaignRepository,
)
from boss_zhipin.platform.boss.targeted_capture import (
    BossTargetedJobSource,
    build_search_routes,
)
from boss_zhipin.website_oper import finding_jobs

log = logging.getLogger(__name__)

DEFAULT_QUERIES = ("AI产品经理", "策略产品经理", "产品经理")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boss-zhipin-daily",
        description="按个人配置跨城市捕捉并筛选岗位，只生成审核队列，不发送消息。",
    )
    parser.add_argument("--per-route", type=int, default=5, help="每个城市/关键词读取数量")
    parser.add_argument("--limit", type=int, default=60, help="本轮最多读取的唯一岗位总数")
    return parser


async def run_daily(*, per_route: int = 5, limit: int = 60) -> dict[str, int]:
    if per_route < 1:
        raise ValueError("per-route limit must be at least 1")
    if limit < 1:
        raise ValueError("capture limit must be at least 1")
    database = Database()
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).get_active()
            if profile is None:
                raise ValueError("还没有 active profile，请先运行一次 capture-only")
            preference = ProfilePreferenceRepository(session).get(profile.id)
            if preference is None:
                raise ValueError("还没有个人筛选配置")
            profile_id = profile.id
            cities = list(preference.target_cities_json)
            filter_config = JobFilterConfig(
                target_cities=tuple(preference.target_cities_json),
                target_roles=tuple(preference.target_roles_json),
                employment_types=tuple(preference.employment_types_json),
                title_excludes=tuple(preference.title_excludes_json),
                content_excludes=tuple(preference.content_excludes_json),
            )
            campaign = SearchCampaignRepository(session).upsert(
                profile_id=profile_id,
                campaign_key=CHINA_CAMPUS_CAMPAIGN.campaign_key,
                name=CHINA_CAMPUS_CAMPAIGN.name,
                source_platforms=list(CHINA_CAMPUS_CAMPAIGN.source_platforms),
                targeting_config={
                    "target_cities": list(preference.target_cities_json),
                    "target_roles": list(preference.target_roles_json),
                    "employment_types": list(preference.employment_types_json),
                },
                action_strategy=CHINA_CAMPUS_CAMPAIGN.action_strategy.value,
            )
            campaign_id = campaign.id

        routes = build_search_routes(cities, list(DEFAULT_QUERIES))
        summary = await CaptureService(database).capture(
            BossTargetedJobSource(routes, per_route_limit=per_route),
            profile_id=profile_id,
            campaign_id=campaign_id,
            limit=limit,
        )
        with database.session() as session:
            jobs = JobRepository(session)
            matches = JobCampaignMatchRepository(session)
            for job_id in summary.job_ids:
                job = jobs.get(job_id)
                if job is None:
                    continue
                assessment = evaluate_job_rules(
                    title=job.title,
                    location=job.location,
                    description=job.description,
                    config=filter_config,
                )
                matches.update_assessment(
                    campaign_id=campaign_id,
                    job_id=job.id,
                    rule_state=assessment.state.value,
                    rule_reasons=list(assessment.reasons),
                    evaluation_policy_version=(
                        CHINA_CAMPUS_CAMPAIGN.evaluation_policy_version
                    ),
                )
        queue = ReviewService(database).list_jobs(limit=100)
        return {
            "observed": summary.observed,
            "created": summary.created,
            "updated": summary.updated,
            "eligible": queue["totalEligible"],
            "needs_review": queue["totalNeedsReview"],
            "filtered": queue["totalFiltered"],
        }
    finally:
        await finding_jobs.shutdown()
        database.close()


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(
        level=os.getenv("LOGLEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    args = build_parser().parse_args(argv)
    try:
        result = uc.loop().run_until_complete(
            run_daily(per_route=args.per_route, limit=args.limit)
        )
    except (TimeoutError, ValueError, RuntimeError) as exc:
        log.error("daily capture 失败：%s", exc)
        return 1
    print(
        "今日筛选完成：观察 {observed}，新增 {created}，已存在 {updated}；"
        "符合 {eligible}，需人工核对 {needs_review}，已过滤 {filtered}。".format(**result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
