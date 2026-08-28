"""Capture-only workflow: observe jobs and persist them without contacting anyone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from boss_zhipin.domain.models import CaptureSummary, JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    AuditEventRepository,
    JobCampaignMatchRepository,
    JobRepository,
    ProfileRepository,
    SearchCampaignRepository,
)


class JobSource(Protocol):
    """Platform boundary implemented by the real browser adapter or a test fake."""

    async def capture_jobs(self, limit: int) -> Sequence[JobSnapshot]: ...


class CaptureService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def capture(
        self,
        source: JobSource,
        *,
        profile_id: str,
        campaign_id: str | None = None,
        source_route: str = "",
        limit: int = 30,
    ) -> CaptureSummary:
        if limit < 1:
            raise ValueError("capture limit must be at least 1")
        snapshots = tuple(await source.capture_jobs(limit))
        if len(snapshots) > limit:
            raise ValueError("job source returned more snapshots than requested")
        return self.ingest(
            profile_id=profile_id,
            campaign_id=campaign_id,
            source_route=source_route,
            snapshots=snapshots,
        )

    def ingest(
        self,
        *,
        profile_id: str,
        campaign_id: str | None = None,
        source_route: str = "",
        snapshots: Sequence[JobSnapshot],
    ) -> CaptureSummary:
        created = 0
        updated = 0
        job_ids: list[str] = []
        with self.database.session() as session:
            if ProfileRepository(session).get(profile_id) is None:
                raise ValueError(f"profile not found: {profile_id}")
            campaign = None
            if campaign_id is not None:
                campaign = SearchCampaignRepository(session).get(campaign_id)
                if campaign is None:
                    raise ValueError(f"campaign not found: {campaign_id}")
                if campaign.profile_id != profile_id:
                    raise ValueError("campaign does not belong to the capture profile")
            jobs = JobRepository(session)
            campaign_matches = JobCampaignMatchRepository(session)
            events = AuditEventRepository(session)
            for snapshot in snapshots:
                if (
                    campaign is not None
                    and snapshot.platform.strip() not in campaign.source_platforms_json
                ):
                    raise ValueError(
                        f"platform {snapshot.platform!r} is not enabled for campaign "
                        f"{campaign.campaign_key!r}"
                    )
                job, was_created = jobs.upsert_snapshot(snapshot)
                job_ids.append(job.id)
                if was_created:
                    created += 1
                else:
                    updated += 1
                if campaign_id is not None:
                    campaign_matches.observe(
                        campaign_id=campaign_id,
                        job_id=job.id,
                        source_route=source_route,
                    )
                events.record(
                    "job_captured" if was_created else "job_seen_again",
                    job_id=job.id,
                    profile_id=profile_id,
                    payload={
                        "canonical_key": job.canonical_key,
                        "campaign_id": campaign_id,
                    },
                )
        return CaptureSummary(
            observed=len(snapshots),
            created=created,
            updated=updated,
            job_ids=tuple(job_ids),
        )
