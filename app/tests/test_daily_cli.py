"""Daily targeted-capture CLI tests."""

from __future__ import annotations

import asyncio

from boss_zhipin import daily_cli
from boss_zhipin.application.targeting_service import TargetingService
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.domain.campaign import CHINA_CAMPUS_CAMPAIGN_KEY
from boss_zhipin.persistence.repositories import (
    JobCampaignMatchRepository,
    ProfileRepository,
    SearchCampaignRepository,
)


def test_daily_parser_defaults():
    args = daily_cli.build_parser().parse_args([])
    assert args.per_route == 5
    assert args.limit == 60


def test_run_daily_captures_and_reports_screening(monkeypatch, tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    with database.session() as session:
        ProfileRepository(session).create(name="2027 campus")
    TargetingService(database).configure_active(
        target_cities=["北京"],
        target_roles=["AI产品经理"],
        employment_types=["2027校招"],
        title_excludes=["销售"],
        content_excludes=["外包"],
        min_match_score=70,
        daily_outreach_limit=12,
        fixed_greeting="你好，我有产品、策略和数据结合的经历，希望进一步了解这个岗位。",
    )

    class FakeSource:
        def __init__(self, routes, *, per_route_limit: int):
            assert len(routes) == 3
            assert per_route_limit == 2

        async def capture_jobs(self, limit: int):
            assert limit == 6
            return (
                JobSnapshot(
                    title="AI产品经理-2027校招",
                    location="北京",
                    description="面向应届毕业生的大模型产品岗位",
                    external_id="job-1",
                ),
            )

    async def shutdown():
        return None

    monkeypatch.setattr(daily_cli, "Database", lambda: database)
    monkeypatch.setattr(daily_cli, "BossTargetedJobSource", FakeSource)
    monkeypatch.setattr(daily_cli.finding_jobs, "shutdown", shutdown)

    result = asyncio.run(daily_cli.run_daily(per_route=2, limit=6))
    assert result["observed"] == 1
    assert result["created"] == 1
    assert result["eligible"] == 1
    with database.session() as session:
        profile = ProfileRepository(session).get_active()
        campaign = SearchCampaignRepository(session).get_by_key(
            profile_id=profile.id,
            campaign_key=CHINA_CAMPUS_CAMPAIGN_KEY,
        )
        matches = JobCampaignMatchRepository(session).list_for_campaign(
            campaign_id=campaign.id
        )
        assert campaign.action_strategy == "boss_fixed_greeting"
        assert [match.rule_state for match in matches] == ["eligible"]
