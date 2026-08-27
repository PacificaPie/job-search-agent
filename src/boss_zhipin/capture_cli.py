"""Standalone capture-only command that never enters the outreach loop."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from pathlib import Path

import nodriver as uc
from dotenv import load_dotenv

from boss_zhipin.application.capture_service import CaptureService
from boss_zhipin.domain.models import CaptureSummary
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import ProfileRepository
from boss_zhipin.platform.boss.capture_source import BossCaptureConfig, BossJobSource
from boss_zhipin.website_oper import finding_jobs

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boss-zhipin-capture",
        description="只捕捉并保存 BOSS 推荐岗位，不发起沟通、不发送消息。",
    )
    parser.add_argument(
        "--limit", type=int, default=30, help="本轮最多捕捉岗位数（默认 30）"
    )
    parser.add_argument(
        "--label", default=None, help="BOSS 求职标签；不传时读取 BOSS_LABEL"
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="SQLite 路径；不传时使用 BOSS_DATABASE_PATH 或 data/reachout.db",
    )
    return parser


async def run_capture_only(
    *,
    limit: int,
    label: str,
    database_path: Path | None = None,
) -> CaptureSummary:
    """Initialize local state and run one read-only browser capture."""

    if limit < 1:
        raise ValueError("capture limit must be at least 1")
    database = Database(database_path)
    database.initialize()
    try:
        with database.session() as session:
            profiles = ProfileRepository(session)
            profile = profiles.get_active()
            if profile is None:
                profile = profiles.create(
                    name=label or "默认求职方向",
                    search_label=label,
                )
            elif label and profile.search_label != label:
                profile.search_label = label
            profile_id = profile.id

        source = BossJobSource(BossCaptureConfig(label=label))
        return await CaptureService(database).capture(
            source,
            profile_id=profile_id,
            limit=limit,
        )
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
    label = args.label if args.label is not None else os.getenv("BOSS_LABEL", "").strip()
    try:
        summary = uc.loop().run_until_complete(
            run_capture_only(
                limit=args.limit,
                label=label,
                database_path=args.database,
            )
        )
    except (TimeoutError, ValueError, RuntimeError) as exc:
        log.error("capture-only 失败：%s", exc)
        return 1
    print(
        f"捕捉完成：观察 {summary.observed}，新增 {summary.created}，"
        f"已存在 {summary.updated}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
