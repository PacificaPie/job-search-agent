"""Capture-only application service tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from sqlalchemy import func, select

from boss_zhipin.application.capture_service import CaptureService
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.domain.campaign import ActionStrategy
from boss_zhipin.persistence.repositories import (
    JobCampaignMatchRepository,
    ProfileRepository,
    SearchCampaignRepository,
)
from boss_zhipin.persistence.schema import AuditEventRow, JobCampaignMatchRow, JobRow


class FakeJobSource:
    def __init__(self, snapshots: Sequence[JobSnapshot]) -> None:
        self.snapshots = snapshots
        self.requested_limit: int | None = None

    async def capture_jobs(self, limit: int) -> Sequence[JobSnapshot]:
        self.requested_limit = limit
        return self.snapshots[:limit]


def _database_with_profile(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    with database.session() as session:
        profile = ProfileRepository(session).create(name="Product roles", display_name="Kai")
        return database, profile.id


def test_capture_creates_then_updates_without_duplicates(tmp_path):
    database, profile_id = _database_with_profile(tmp_path)
    service = CaptureService(database)
    snapshots = [
        JobSnapshot(title="AI PM", company="A", external_id="one", description="Agents"),
        JobSnapshot(title="LLM PM", company="B", external_id="two", description="RAG"),
    ]
    source = FakeJobSource(snapshots)
    try:
        first = asyncio.run(service.capture(source, profile_id=profile_id, limit=30))
        second = asyncio.run(service.capture(source, profile_id=profile_id, limit=30))
        assert source.requested_limit == 30
        assert (first.observed, first.created, first.updated) == (2, 2, 0)
        assert (second.observed, second.created, second.updated) == (2, 0, 2)
        assert first.job_ids == second.job_ids

        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(JobRow)) == 2
            assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 4
            event_types = list(
                session.scalars(select(AuditEventRow.event_type).order_by(AuditEventRow.created_at))
            )
            assert event_types.count("job_captured") == 2
            assert event_types.count("job_seen_again") == 2
    finally:
        database.close()


def test_capture_rejects_unknown_profile(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    service = CaptureService(database)
    source = FakeJobSource([JobSnapshot(title="AI PM")])
    try:
        try:
            asyncio.run(service.capture(source, profile_id="missing"))
        except ValueError as exc:
            assert "profile not found" in str(exc)
        else:
            raise AssertionError("unknown profile should fail")
    finally:
        database.close()


def test_capture_rejects_invalid_limit(tmp_path):
    database, profile_id = _database_with_profile(tmp_path)
    try:
        service = CaptureService(database)
        try:
            asyncio.run(service.capture(FakeJobSource([]), profile_id=profile_id, limit=0))
        except ValueError as exc:
            assert "at least 1" in str(exc)
        else:
            raise AssertionError("zero limit should fail")
    finally:
        database.close()


def test_capture_records_campaign_membership_without_duplicating_job(tmp_path):
    database, profile_id = _database_with_profile(tmp_path)
    try:
        with database.session() as session:
            campaign = SearchCampaignRepository(session).upsert(
                profile_id=profile_id,
                campaign_key="cn-2027-ai-product",
                name="国内校招",
                source_platforms=["boss_zhipin"],
                targeting_config={"cities": ["北京"]},
                action_strategy=ActionStrategy.BOSS_FIXED_GREETING.value,
            )
            campaign_id = campaign.id

        service = CaptureService(database)
        snapshot = JobSnapshot(title="AI PM", company="A", external_id="one")
        first = asyncio.run(
            service.capture(
                FakeJobSource([snapshot]),
                profile_id=profile_id,
                campaign_id=campaign_id,
                source_route="北京 / AI 产品经理",
            )
        )
        second = asyncio.run(
            service.capture(
                FakeJobSource([snapshot]),
                profile_id=profile_id,
                campaign_id=campaign_id,
            )
        )

        with database.session() as session:
            match = JobCampaignMatchRepository(session).get(
                campaign_id=campaign_id,
                job_id=first.job_ids[0],
            )
            assert first.job_ids == second.job_ids
            assert match.source_route == "北京 / AI 产品经理"
            assert session.scalar(select(func.count()).select_from(JobRow)) == 1
            assert session.scalar(select(func.count()).select_from(JobCampaignMatchRow)) == 1
    finally:
        database.close()


def test_capture_rejects_platform_outside_campaign(tmp_path):
    database, profile_id = _database_with_profile(tmp_path)
    try:
        with database.session() as session:
            campaign = SearchCampaignRepository(session).upsert(
                profile_id=profile_id,
                campaign_key="cn-2027-ai-product",
                name="国内校招",
                source_platforms=["boss_zhipin"],
                targeting_config={},
                action_strategy=ActionStrategy.BOSS_FIXED_GREETING.value,
            )
            campaign_id = campaign.id

        try:
            asyncio.run(
                CaptureService(database).capture(
                    FakeJobSource([JobSnapshot(platform="linkedin", title="AI PM")]),
                    profile_id=profile_id,
                    campaign_id=campaign_id,
                )
            )
        except ValueError as exc:
            assert "not enabled for campaign" in str(exc)
        else:
            raise AssertionError("campaign should reject a platform outside its sources")

        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(JobRow)) == 0
    finally:
        database.close()
