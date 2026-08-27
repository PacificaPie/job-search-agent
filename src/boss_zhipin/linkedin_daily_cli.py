"""Daily free local LinkedIn capture for approved US new-grad targets; never sends."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from boss_zhipin.application.capture_service import CaptureService, JobSource
from boss_zhipin.domain.job_filter import RuleState
from boss_zhipin.domain.linkedin_filter import evaluate_linkedin_job_rules
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import JobRepository, ProfileRepository
from boss_zhipin.platform.linkedin.cli_source import (
    LinkedInCliJobSource,
    LinkedInCliRunner,
    build_search_routes,
)

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-job-daily",
        description="本地搜索美国 LinkedIn 2027 New Grad + Sponsorship 岗位，只写审核队列。",
    )
    parser.add_argument("--per-route", type=int, default=3, help="每个地点/关键词最多读取数量")
    parser.add_argument("--limit", type=int, default=30, help="本轮最多读取的唯一岗位总数")
    parser.add_argument("--project", type=Path, default=None, help="免费 linkedin-cli 项目路径")
    parser.add_argument("--database", type=Path, default=None, help="SQLite 数据库路径")
    return parser


async def run_linkedin_daily(
    *,
    per_route: int = 3,
    limit: int = 30,
    project_path: Path | None = None,
    database_path: Path | None = None,
    source: JobSource | None = None,
) -> dict[str, int]:
    """Capture LinkedIn jobs and return batch-specific deterministic screening counts."""
    if per_route < 1:
        raise ValueError("per-route limit must be at least 1")
    if limit < 1:
        raise ValueError("capture limit must be at least 1")
    database = Database(database_path)
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).get_active()
            if profile is None:
                profile = ProfileRepository(session).create(name="2027 global new grad")
            profile_id = profile.id
        capture_source = source or LinkedInCliJobSource(
            LinkedInCliRunner(project_path),
            build_search_routes(),
            per_route_limit=per_route,
        )
        summary = await CaptureService(database).capture(
            capture_source,
            profile_id=profile_id,
            limit=limit,
        )
        counts = {state.value: 0 for state in RuleState}
        with database.session() as session:
            jobs = JobRepository(session)
            for job_id in summary.job_ids:
                job = jobs.get(job_id)
                if job is None:
                    continue
                match = evaluate_linkedin_job_rules(
                    title=job.title,
                    location=job.location,
                    description=job.description,
                )
                counts[match.state.value] += 1
        return {
            "observed": summary.observed,
            "created": summary.created,
            "updated": summary.updated,
            "eligible": counts[RuleState.ELIGIBLE.value],
            "needs_review": counts[RuleState.NEEDS_REVIEW.value],
            "filtered": counts[RuleState.FILTERED.value],
        }
    finally:
        database.close()


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(
            run_linkedin_daily(
                per_route=args.per_route,
                limit=args.limit,
                project_path=args.project,
                database_path=args.database,
            )
        )
    except (TimeoutError, ValueError, RuntimeError) as exc:
        log.error("LinkedIn daily capture 失败：%s", exc)
        return 1
    print(
        "LinkedIn 筛选完成：观察 {observed}，新增 {created}，已存在 {updated}；"
        "符合 {eligible}，需人工核对 {needs_review}，已过滤 {filtered}。".format(**result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

