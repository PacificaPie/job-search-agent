"""Capture-only workflow: observe jobs and persist them without contacting anyone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from boss_zhipin.domain.models import CaptureSummary, JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import AuditEventRepository, JobRepository, ProfileRepository


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
        limit: int = 30,
    ) -> CaptureSummary:
        if limit < 1:
            raise ValueError("capture limit must be at least 1")
        snapshots = tuple(await source.capture_jobs(limit))
        if len(snapshots) > limit:
            raise ValueError("job source returned more snapshots than requested")
        return self.ingest(profile_id=profile_id, snapshots=snapshots)

    def ingest(
        self,
        *,
        profile_id: str,
        snapshots: Sequence[JobSnapshot],
    ) -> CaptureSummary:
        created = 0
        updated = 0
        job_ids: list[str] = []
        with self.database.session() as session:
            if ProfileRepository(session).get(profile_id) is None:
                raise ValueError(f"profile not found: {profile_id}")
            jobs = JobRepository(session)
            events = AuditEventRepository(session)
            for snapshot in snapshots:
                job, was_created = jobs.upsert_snapshot(snapshot)
                job_ids.append(job.id)
                if was_created:
                    created += 1
                else:
                    updated += 1
                events.record(
                    "job_captured" if was_created else "job_seen_again",
                    job_id=job.id,
                    profile_id=profile_id,
                    payload={"canonical_key": job.canonical_key},
                )
        return CaptureSummary(
            observed=len(snapshots),
            created=created,
            updated=updated,
            job_ids=tuple(job_ids),
        )
