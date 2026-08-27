"""Human review workflow tests."""

from sqlalchemy import func, select

from boss_zhipin.application.application_service import ApplicationService
from boss_zhipin.application.draft_service import DraftService
from boss_zhipin.application.evaluation_service import EvaluationService
from boss_zhipin.application.review_service import ReviewService
from boss_zhipin.application.targeting_service import TargetingService
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import JobRepository, ProfileRepository
from boss_zhipin.persistence.schema import AuditEventRow


def _seed(database: Database) -> tuple[str, str]:
    with database.session() as session:
        profile = ProfileRepository(session).create(name="AI roles")
        job, _ = JobRepository(session).upsert_snapshot(
            JobSnapshot(
                title="AI 产品经理",
                company="Example",
                # 显式给个非目标城市：空 location 现在会走「正文推断城市 → 未知则降级人工」
                # 的分支（见 test_job_filter 的 blank_location 用例），会让下面几条
                # 关于定向规则和校招标识的断言变得依赖那条兜底逻辑。
                location="杭州",
                description="负责 AI 产品规划和落地",
                external_id="job-1",
            )
        )
        return profile.id, job.id


def test_evaluate_generate_edit_and_approve(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        evaluation_id = EvaluationService(database).evaluate(
            job_id=job_id,
            profile_id=profile_id,
            evaluator=lambda description: {
                "score": 86,
                "reason": "AI 产品经验匹配",
                "matched_keywords": ["AI", "产品"],
            },
            model="test-model",
        )
        draft_id = DraftService(database).generate(
            job_id=job_id,
            profile_id=profile_id,
            generator=lambda description: (
                "你好，我有 AI 产品从规划到落地的完整经验，也做过复杂项目协作，"
                "想进一步了解这个岗位当前负责的业务方向。"
            ),
        )

        service = ReviewService(database)
        queue = service.list_jobs()
        assert queue["total"] == 1
        assert queue["items"][0]["evaluation"]["id"] == evaluation_id
        assert queue["items"][0]["draft"]["id"] == draft_id
        assert queue["items"][0]["draft"]["reviewState"] == "pending"

        approved = service.decide(draft_id=draft_id, decision="approve")
        assert approved["reviewState"] == "approved"
        assert approved["approvedAt"] is not None
        # 批准同时开一条投递记录（preparing），但不代表已发送
        assert approved["applicationStatus"] == "preparing"
        application = ApplicationService(database).get_for_job(job_id)
        assert application is not None
        assert application["id"] == approved["applicationId"]
        assert application["draftId"] == draft_id
        assert application["channel"] == "boss_chat"
        assert [entry["status"] for entry in application["statusHistory"]] == ["preparing"]

        edited = service.update_draft(
            draft_id=draft_id,
            content=(
                "你好，我有 AI 产品从规划到落地的经验，近期也在持续做智能体项目，"
                "想了解一下这个岗位当前最核心的业务目标。"
            ),
        )
        assert edited["reviewState"] == "pending"
        assert edited["revision"] == 2
        assert edited["approvedAt"] is None

        with database.session() as session:
            # evaluation / draft_generated / draft_approved / application_created / draft_edited
            assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 5
            event_types = set(session.scalars(select(AuditEventRow.event_type)))
            assert "application_created" in event_types
    finally:
        database.close()


def test_invalid_draft_cannot_be_approved(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, job_id = _seed(database)
        draft_id = DraftService(database).generate(
            job_id=job_id,
            profile_id=profile_id,
            generator=lambda description: "太短",
        )
        service = ReviewService(database)

        try:
            service.decide(draft_id=draft_id, decision="approve")
        except ValueError as exc:
            assert "pass validation" in str(exc)
        else:
            raise AssertionError("invalid draft should not be approved")
    finally:
        database.close()


def test_review_queue_validates_pagination(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        service = ReviewService(database)
        for kwargs in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
            try:
                service.list_jobs(**kwargs)
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected invalid pagination for {kwargs}")
    finally:
        database.close()


def test_review_queue_applies_active_targeting_rules(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        profile_id, _ = _seed(database)
        with database.session() as session:
            JobRepository(session).upsert_snapshot(
                JobSnapshot(
                    title="AI 产品经理（2027校招）",
                    company="Example AI",
                    location="上海",
                    description="面向应届毕业生，负责大模型产品落地",
                    external_id="eligible-job",
                )
            )
            JobRepository(session).upsert_snapshot(
                JobSnapshot(
                    title="产品运营（2027校招）",
                    company="Example",
                    location="上海",
                    description="负责产品运营",
                    external_id="filtered-job",
                )
            )
        configured = TargetingService(database).configure_active(
            target_cities=["北京", "上海", "深圳", "广州"],
            target_roles=["AI 产品经理", "产品经理"],
            employment_types=["2027校招"],
            title_excludes=["销售", "运营", "实施"],
            content_excludes=["外包", "驻场"],
            min_match_score=70,
            daily_outreach_limit=12,
            fixed_greeting="你好，我有产品、策略和数据结合的经历，希望进一步了解这个岗位。",
        )
        assert configured["profileId"] == profile_id

        queue = ReviewService(database).list_jobs()
        assert queue["totalCaptured"] == 3
        assert queue["totalEligible"] == 1
        assert queue["totalNeedsReview"] == 0
        assert queue["totalFiltered"] == 2
        assert [item["job"]["title"] for item in queue["items"]] == [
            "AI 产品经理（2027校招）"
        ]
        assert queue["items"][0]["ruleMatch"]["matchedCity"] == "上海"
    finally:
        database.close()


def test_review_queue_shows_jobs_without_explicit_campus_signal_for_manual_check(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        _seed(database)
        TargetingService(database).configure_active(
            target_cities=["北京"],
            target_roles=["产品经理"],
            employment_types=["2027校招"],
            title_excludes=[],
            content_excludes=[],
            min_match_score=70,
            daily_outreach_limit=12,
            fixed_greeting="你好，我有产品、策略和数据结合的经历，希望进一步了解这个岗位。",
        )
        with database.session() as session:
            JobRepository(session).upsert_snapshot(
                JobSnapshot(
                    title="产品经理",
                    location="北京",
                    description="负责互联网产品规划",
                    external_id="unclear-campus-job",
                )
            )

        queue = ReviewService(database).list_jobs()
        assert queue["total"] == 1
        assert queue["totalNeedsReview"] == 1
        assert queue["items"][0]["ruleMatch"]["state"] == "needs_review"
    finally:
        database.close()
