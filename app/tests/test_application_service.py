"""投递记录服务测试：状态机流转 + 审计留痕 + 指标原始字段。"""

import pytest
from sqlalchemy import func, select

from boss_zhipin.application.application_service import ApplicationService
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    JobRepository,
    ProfileRepository,
    ResumeVersionRepository,
)
from boss_zhipin.persistence.schema import AuditEventRow


def _seed(database: Database) -> tuple[str, str]:
    with database.session() as session:
        profile = ProfileRepository(session).create(name="AI roles")
        job, _ = JobRepository(session).upsert_snapshot(
            JobSnapshot(
                title="AI 产品经理",
                company="Example",
                location="北京",
                description="面向2027届校招",
                external_id="job-1",
            )
        )
        return profile.id, job.id


def test_create_is_idempotent_per_job(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        service = ApplicationService(database)
        first = service.create(job_id=job_id, profile_id=profile_id)
        second = service.create(job_id=job_id, profile_id=profile_id)
        assert first["id"] == second["id"]
        assert first["status"] == "preparing"
        assert first["allowedTransitions"] == ["ready", "withdrawn"]
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 1
    finally:
        database.close()


def test_create_rejects_unknown_job_and_channel(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        _, job_id = _seed(database)
        service = ApplicationService(database)
        with pytest.raises(ValueError, match="job not found"):
            service.create(job_id="missing-job")
        with pytest.raises(ValueError, match="unsupported application channel"):
            service.create(job_id=job_id, channel="carrier_pigeon")
    finally:
        database.close()


def test_advance_records_history_timestamps_and_audit(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        service = ApplicationService(database)
        application_id = service.create(job_id=job_id, profile_id=profile_id)["id"]

        service.advance(application_id=application_id, status="ready")
        submitted = service.advance(
            application_id=application_id, status="submitted", note="本人在 BOSS 手动发送"
        )
        assert submitted["submittedAt"] is not None
        assert submitted["firstResponseAt"] is None

        screening = service.advance(
            application_id=application_id,
            status="screening",
            next_action="等 HR 约初面",
        )
        # 对方有回应 → 回调率的分子
        assert screening["firstResponseAt"] is not None
        assert screening["nextAction"] == "等 HR 约初面"

        assert [entry["status"] for entry in screening["statusHistory"]] == [
            "preparing",
            "ready",
            "submitted",
            "screening",
        ]
        assert screening["statusHistory"][2]["note"] == "本人在 BOSS 手动发送"

        with database.session() as session:
            changed = session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.event_type == "application_status_changed"
                )
            ).all()
            assert len(changed) == 3
            assert changed[-1].payload_json["from"] == "submitted"
            assert changed[-1].payload_json["to"] == "screening"
    finally:
        database.close()


def test_illegal_transition_changes_nothing(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        _, job_id = _seed(database)
        service = ApplicationService(database)
        application_id = service.create(job_id=job_id)["id"]
        with pytest.raises(ValueError, match="不允许的状态流转"):
            service.advance(application_id=application_id, status="offer")
        current = service.get_for_job(job_id)
        assert current["status"] == "preparing"
        assert len(current["statusHistory"]) == 1
        with database.session() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEventRow)
                    .where(AuditEventRow.event_type == "application_status_changed")
                )
                == 0
            )
    finally:
        database.close()


def test_list_filters_by_status_and_counts(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        _, job_id = _seed(database)
        with database.session() as session:
            JobRepository(session).upsert_snapshot(
                JobSnapshot(title="数据产品经理", location="上海", external_id="job-2")
            )
            other_job_id = JobRepository(session).list_recent(offset=0, limit=10)[0].id
        service = ApplicationService(database)
        first = service.create(job_id=job_id)["id"]
        service.create(job_id=other_job_id)
        service.advance(application_id=first, status="ready")

        listing = service.list()
        assert listing["countsByStatus"] == {"preparing": 1, "ready": 1}
        assert listing["items"][0]["job"]["title"]

        ready_only = service.list(statuses=("ready",))
        assert [item["id"] for item in ready_only["items"]] == [first]

        with pytest.raises(ValueError, match="unknown application status"):
            service.list(statuses=("hired",))
    finally:
        database.close()


def test_resume_version_can_be_attached_and_language_is_checked(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        with database.session() as session:
            versions = ResumeVersionRepository(session)
            version = versions.create(
                job_id=job_id,
                profile_id=profile_id,
                archive_entry_ids=["A1", "B2"],
                lang="en",
                pdf_path="/tmp/resume.pdf",
            )
            version_id = version.id
            with pytest.raises(ValueError, match="unsupported resume language"):
                versions.create(job_id=job_id, lang="fr")

        application = ApplicationService(database).create(
            job_id=job_id, profile_id=profile_id, resume_version_id=version_id
        )
        assert application["resumeVersionId"] == version_id
        with database.session() as session:
            stored = ResumeVersionRepository(session).latest_for_job(job_id)
            assert stored.archive_entry_ids_json == ["A1", "B2"]
            assert stored.lang == "en"
    finally:
        database.close()
