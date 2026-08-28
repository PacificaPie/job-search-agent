"""LinkedIn daily capture command tests."""

from __future__ import annotations

import asyncio

from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.domain.campaign import GLOBAL_NEW_GRAD_CAMPAIGN_KEY
from boss_zhipin.linkedin_daily_cli import build_parser, run_linkedin_daily
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    JobCampaignMatchRepository,
    ProfileRepository,
    SearchCampaignRepository,
)


class FakeSource:
    async def capture_jobs(self, limit: int):
        assert limit == 5
        return (
            JobSnapshot(
                platform="linkedin",
                external_id="li-1",
                title="AI Product Manager, New Grad",
                company="Example AI",
                location="New York, NY",
                description="2027 new grad. Visa sponsorship is available.",
            ),
            JobSnapshot(
                platform="linkedin",
                external_id="li-2",
                title="AI Product Manager",
                company="No Visa Inc",
                location="Boston, MA",
                description="2027 new grad. Unable to sponsor now or in the future.",
            ),
        )


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.per_route == 3
    assert args.limit == 30


def test_daily_capture_reports_batch_screening(tmp_path):
    database_path = tmp_path / "reachout.db"
    result = asyncio.run(
        run_linkedin_daily(
            per_route=2,
            limit=5,
            database_path=database_path,
            source=FakeSource(),
        )
    )
    assert result["observed"] == 2
    assert result["eligible"] == 1
    assert result["filtered"] == 1
    database = Database(database_path)
    try:
        with database.session() as session:
            profile = ProfileRepository(session).get_active()
            campaign = SearchCampaignRepository(session).get_by_key(
                profile_id=profile.id,
                campaign_key=GLOBAL_NEW_GRAD_CAMPAIGN_KEY,
            )
            states = {
                match.rule_state
                for match in JobCampaignMatchRepository(session).list_for_campaign(
                    campaign_id=campaign.id
                )
            }
            assert campaign.action_strategy == "tailored_application"
            assert states == {"eligible", "filtered"}
    finally:
        database.close()
