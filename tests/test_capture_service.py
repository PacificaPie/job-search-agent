"""Capture-only application service tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from sqlalchemy import func, select

from boss_zhipin.application.capture_service import CaptureService
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import ProfileRepository
from boss_zhipin.persistence.schema import AuditEventRow, JobRow


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
