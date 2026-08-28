"""SQLite lifecycle and repository tests."""

from sqlalchemy import func, select, text

from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.domain.campaign import ActionStrategy
from boss_zhipin.persistence.database import Database, default_database_path
from boss_zhipin.persistence.migrations import MIGRATIONS
from boss_zhipin.persistence.repositories import (
    AuditEventRepository,
    JobCampaignMatchRepository,
    JobRepository,
    ProfilePreferenceRepository,
    ProfileRepository,
    SearchCampaignRepository,
)
from boss_zhipin.persistence.schema import (
    AuditEventRow,
    DraftRow,
    EvaluationRow,
    JobRow,
    JobCampaignMatchRow,
    ProfilePreferenceRow,
    ProfileRow,
    SearchCampaignRow,
)


def test_default_database_path_can_be_overridden(monkeypatch, tmp_path):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("BOSS_DATABASE_PATH", str(target))
    assert default_database_path() == target


def test_initialize_is_versioned_and_idempotent(tmp_path):
    database = Database(tmp_path / "reachout.db")
    try:
        assert database.initialize() == (1, 2, 3, 4, 5)
        assert database.initialize() == ()
        with database.engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            assert {
                "schema_migrations",
                "profiles",
                "jobs",
                "audit_events",
                "evaluations",
                "drafts",
                "profile_preferences",
                "resume_versions",
                "applications",
                "search_campaigns",
                "job_campaign_matches",
            } <= tables
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    finally:
        database.close()


def test_existing_v1_database_upgrades_without_losing_jobs(tmp_path):
    database = Database(tmp_path / "reachout.db")
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE schema_migrations ("
                    "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT)"
                )
            )
            MIGRATIONS[0].apply(connection)
            connection.execute(
                text(
                    "INSERT INTO schema_migrations(version, name, applied_at) "
                    "VALUES (1, 'initial local-first schema', CURRENT_TIMESTAMP)"
                )
            )
        with database.session() as session:
            ProfileRepository(session).create(name="Existing profile")
            job, _ = JobRepository(session).upsert_snapshot(
                JobSnapshot(
                    title="Existing job",
                    description="Existing JD",
                    external_id="old-1",
                )
            )
            job_id = job.id

        assert database.initialize() == (2, 3, 4, 5)
        with database.session() as session:
            assert JobRepository(session).get(job_id).title == "Existing job"
            assert session.scalar(select(func.count()).select_from(EvaluationRow)) == 0
            assert session.scalar(select(func.count()).select_from(DraftRow)) == 0
    finally:
        database.close()


def test_campaigns_separate_search_intent_from_canonical_jobs(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).create(name="AI product roles")
            campaigns = SearchCampaignRepository(session)
            china = campaigns.upsert(
                profile_id=profile.id,
                campaign_key="cn-2027-ai-product",
                name="国内校招",
                source_platforms=["boss_zhipin", "boss_zhipin"],
                targeting_config={"cities": ["北京", "上海"]},
                action_strategy=ActionStrategy.BOSS_FIXED_GREETING.value,
            )
            global_campaign = campaigns.upsert(
                profile_id=profile.id,
                campaign_key="global-2027-ai-product",
                name="海外 New Grad",
                source_platforms=["linkedin", "company_site"],
                targeting_config={"sponsorship_required": True},
                action_strategy=ActionStrategy.TAILORED_APPLICATION.value,
            )
            job, _ = JobRepository(session).upsert_snapshot(
                JobSnapshot(
                    title="AI Product Manager",
                    company="Example",
                    external_id="shared-job",
                )
            )
            matches = JobCampaignMatchRepository(session)
            matches.observe(campaign_id=china.id, job_id=job.id, source_route="北京 / AI PM")
            matches.update_assessment(
                campaign_id=china.id,
                job_id=job.id,
                rule_state="eligible",
                rule_reasons=["城市：北京"],
                score=82,
                evaluation_policy_version="boss-rules-v1",
            )
            matches.observe(campaign_id=global_campaign.id, job_id=job.id)
            profile_id = profile.id
            job_id = job.id
            china_id = china.id

        with database.session() as session:
            campaigns = SearchCampaignRepository(session).list_active(profile_id=profile_id)
            assert [campaign.campaign_key for campaign in campaigns] == [
                "cn-2027-ai-product",
                "global-2027-ai-product",
            ]
            assert campaigns[0].source_platforms_json == ["boss_zhipin"]
            match = JobCampaignMatchRepository(session).get(
                campaign_id=china_id,
                job_id=job_id,
            )
            assert match.rule_state == "eligible"
            assert match.score == 82
            assert session.scalar(select(func.count()).select_from(SearchCampaignRow)) == 2
            assert session.scalar(select(func.count()).select_from(JobCampaignMatchRow)) == 2
            assert session.scalar(select(func.count()).select_from(JobRow)) == 1
    finally:
        database.close()


def test_campaign_repository_rejects_ambiguous_identity_and_strategy(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).create(name="AI roles")
            campaigns = SearchCampaignRepository(session)
            try:
                campaigns.upsert(
                    profile_id=profile.id,
                    campaign_key="China Campaign",
                    name="国内校招",
                    source_platforms=["boss_zhipin"],
                    targeting_config={},
                    action_strategy=ActionStrategy.BOSS_FIXED_GREETING.value,
                )
            except ValueError as exc:
                assert "kebab-case" in str(exc)
            else:
                raise AssertionError("ambiguous campaign key should fail")

            try:
                campaigns.upsert(
                    profile_id=profile.id,
                    campaign_key="cn-campus",
                    name="国内校招",
                    source_platforms=["boss_zhipin"],
                    targeting_config={},
                    action_strategy="auto_send",
                )
            except ValueError as exc:
                assert "unsupported campaign action strategy" in str(exc)
            else:
                raise AssertionError("unknown action strategy should fail")
    finally:
        database.close()


def test_profile_preferences_are_validated_and_deduplicated(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).create(name="2027 campus")
            preference = ProfilePreferenceRepository(session).upsert(
                profile_id=profile.id,
                target_cities=["北京", "上海", "北京", ""],
                target_roles=["AI产品经理", "产品经理"],
                employment_types=["2027校招"],
                title_excludes=["销售", "运营"],
                content_excludes=["外包", "驻场"],
                min_match_score=70,
                daily_outreach_limit=12,
                fixed_greeting="你好，我有产品、策略和数据结合的经历，希望进一步了解这个岗位。",
            )
            profile_id = profile.id
            assert preference.target_cities_json == ["北京", "上海"]

        with database.session() as session:
            stored = ProfilePreferenceRepository(session).get(profile_id)
            assert stored.daily_outreach_limit == 12
            assert stored.min_match_score == 70
            assert session.scalar(select(func.count()).select_from(ProfilePreferenceRow)) == 1
    finally:
        database.close()


def test_review_repositories_store_latest_evaluation_and_draft(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).create(name="AI roles")
            job, _ = JobRepository(session).upsert_snapshot(
                JobSnapshot(title="AI PM", description="Build AI products", external_id="job-1")
            )
            from boss_zhipin.persistence.repositories import DraftRepository, EvaluationRepository

            evaluation = EvaluationRepository(session).create(
                job_id=job.id,
                profile_id=profile.id,
                score=88,
                reason="经历匹配",
            )
            draft = DraftRepository(session).create(
                job_id=job.id,
                profile_id=profile.id,
                content="你好，我做过多个 AI 产品项目，希望和你了解一下这个岗位的业务方向。",
                validation_ok=True,
            )
            job_id = job.id

        with database.session() as session:
            from boss_zhipin.persistence.repositories import DraftRepository, EvaluationRepository

            assert EvaluationRepository(session).latest_for_job(job_id).id == evaluation.id
            assert DraftRepository(session).latest_for_job(job_id).id == draft.id
            assert session.scalar(select(func.count()).select_from(EvaluationRow)) == 1
            assert session.scalar(select(func.count()).select_from(DraftRow)) == 1
    finally:
        database.close()


def test_job_upsert_preserves_identity_and_updates_mutable_fields(tmp_path):
    database = Database(tmp_path / "reachout.db")
    database.initialize()
    try:
        with database.session() as session:
            profile = ProfileRepository(session).create(name="AI roles")
            profile_id = profile.id
            jobs = JobRepository(session)
            first, created = jobs.upsert_snapshot(
                JobSnapshot(
                    title="AI PM",
                    company="Example",
                    salary="20-30K",
                    description="Build agents",
                    external_id="job-1",
                )
            )
            first_seen = first.first_seen_at
            job_id = first.id
            assert created is True

        with database.session() as session:
            updated, created = JobRepository(session).upsert_snapshot(
                JobSnapshot(
                    title="Senior AI PM",
                    company="Example",
                    salary="25-35K",
                    description="Build agents and RAG",
                    external_id="job-1",
                )
            )
            assert created is False
            assert updated.id == job_id
            assert updated.title == "Senior AI PM"
            assert updated.salary == "25-35K"
            assert updated.first_seen_at == first_seen
            AuditEventRepository(session).record(
                "job_seen_again", job_id=updated.id, profile_id=profile_id
            )

        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(ProfileRow)) == 1
            assert session.scalar(select(func.count()).select_from(JobRow)) == 1
            assert session.scalar(select(func.count()).select_from(AuditEventRow)) == 1
    finally:
        database.close()
