"""从数据库现状读 DailyState + plan CLI 的报告拼装。"""

from boss_zhipin.agent.plan_cli import build_report, render
from boss_zhipin.agent.state import collect_state
from boss_zhipin.agent.tools import build_default_registry
from boss_zhipin.application.application_service import ApplicationService
from boss_zhipin.application.draft_service import DraftService
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import JobRepository, ProfileRepository


def _seed(database: Database) -> tuple[str, str]:
    with database.session() as session:
        profile = ProfileRepository(session).create(name="AI roles")
        job, _ = JobRepository(session).upsert_snapshot(
            JobSnapshot(
                title="AI 产品经理",
                company="Example",
                location="北京",
                description="面向2027届校招，负责大模型产品",
                external_id="job-1",
            )
        )
        return profile.id, job.id


def test_collect_state_counts_pending_drafts_and_applications(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        DraftService(database).generate(
            job_id=job_id,
            profile_id=profile_id,
            generator=lambda description: (
                "你好，我有 AI 产品从规划到落地的完整经验，也做过复杂项目协作，"
                "想进一步了解这个岗位当前负责的业务方向。"
            ),
        )
        ApplicationService(database).create(job_id=job_id, profile_id=profile_id)

        state = collect_state(build_default_registry(database), daily_quota=12)
        assert state.eligible == 1
        assert state.drafts_pending == 1
        # preparing 计入「已批准/准备中但还没投出去」
        assert state.approved_not_submitted == 1
        assert state.submitted_awaiting_response == 0
        assert state.remaining_daily_quota == 12
    finally:
        database.close()


def test_stale_submission_is_detected_by_threshold(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        service = ApplicationService(database)
        application_id = service.create(job_id=job_id, profile_id=profile_id)["id"]
        service.advance(application_id=application_id, status="ready")
        service.advance(application_id=application_id, status="submitted")

        registry = build_default_registry(database)
        # 刚投出去：在等，但还没超期
        fresh = collect_state(registry, ghost_after_days=14)
        assert fresh.submitted_awaiting_response == 1
        assert fresh.stale_awaiting_response == 0
        assert fresh.remaining_daily_quota == 11

        # 阈值设成 0 天 → 立刻算超期，不用去改数据库里的时间
        stale = collect_state(registry, ghost_after_days=0)
        assert stale.stale_awaiting_response == 1
    finally:
        database.close()


def test_build_report_and_render_are_readonly(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        _seed(database)
        report = build_report(database)
        assert report["state"]["eligible"] == 1
        assert report["actions"]
        assert "list_review_queue" in report["readonlyTools"]
        text = render(report)
        assert "今日操盘建议" in text
        assert "不会发送" in text
        # 生成报告不产生任何投递记录
        assert ApplicationService(database).list()["countsByStatus"] == {}
    finally:
        database.close()


def test_pending_migrations_is_empty_after_initialize(tmp_path):
    database = Database(tmp_path / "reachout.db")
    try:
        assert database.pending_migrations() == (1, 2, 3, 4, 5)
        database.initialize()
        assert database.pending_migrations() == ()
    finally:
        database.close()
