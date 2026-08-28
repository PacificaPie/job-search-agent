"""Human-review queue and state transitions for outreach drafts."""

from __future__ import annotations

from typing import Any

from boss_zhipin.audit import validate_letter
from boss_zhipin.domain.application_status import ApplicationChannel, ApplicationStatus
from boss_zhipin.domain.enums import ReviewDecision, ReviewState
from boss_zhipin.domain.job_filter import JobFilterConfig, RuleMatch, RuleState, evaluate_job_rules
from boss_zhipin.domain.linkedin_filter import evaluate_linkedin_job_rules
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    ApplicationRepository,
    AuditEventRepository,
    DraftRepository,
    EvaluationRepository,
    JobRepository,
    ProfilePreferenceRepository,
    ProfileRepository,
)
from boss_zhipin.persistence.schema import utc_now


class ReviewService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_jobs(self, *, offset: int = 0, limit: int = 30) -> dict[str, Any]:
        """Return a paged review projection with the latest evaluation and draft."""

        if offset < 0:
            raise ValueError("offset cannot be negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self.database.session() as session:
            jobs_repo = JobRepository(session)
            evaluations = EvaluationRepository(session)
            drafts = DraftRepository(session)
            profile = ProfileRepository(session).get_active()
            preference = (
                ProfilePreferenceRepository(session).get(profile.id)
                if profile is not None
                else None
            )
            config = self._filter_config(preference)
            all_items = []
            total_eligible = 0
            total_needs_review = 0
            total_filtered = 0
            for job in jobs_repo.list_recent(offset=0, limit=10_000):
                evaluation = evaluations.latest_for_job(job.id)
                draft = drafts.latest_for_job(job.id)
                if job.platform == "linkedin":
                    rule_match = evaluate_linkedin_job_rules(
                        title=job.title,
                        location=job.location,
                        description=job.description,
                    )
                else:
                    rule_match = evaluate_job_rules(
                        title=job.title,
                        location=job.location,
                        description=job.description,
                        config=config,
                    )
                if (
                    preference is not None
                    and evaluation is not None
                    and evaluation.score is not None
                    and evaluation.score < preference.min_match_score
                ):
                    rule_match = RuleMatch(
                        RuleState.FILTERED,
                        (f"匹配分 {evaluation.score} 低于门槛 {preference.min_match_score}",),
                        rule_match.matched_city,
                        rule_match.matched_role,
                        rule_match.matched_employment_type,
                    )
                if rule_match.state is RuleState.ELIGIBLE:
                    total_eligible += 1
                elif rule_match.state is RuleState.NEEDS_REVIEW:
                    total_needs_review += 1
                else:
                    total_filtered += 1
                    continue
                all_items.append(
                    {
                        "job": {
                            "id": job.id,
                            "platform": job.platform,
                            "title": job.title,
                            "company": job.company,
                            "location": job.location,
                            "salary": job.salary,
                            "description": job.description,
                            "sourceUrl": job.source_url,
                            "lastSeenAt": job.last_seen_at.isoformat(),
                        },
                        "evaluation": None if evaluation is None else {
                            "id": evaluation.id,
                            "score": evaluation.score,
                            "reason": evaluation.reason,
                            "keywordMatches": evaluation.keyword_matches_json,
                            "degraded": evaluation.degraded,
                        },
                        "draft": None if draft is None else self._draft_dict(draft),
                        "ruleMatch": self._rule_match_dict(rule_match),
                    }
                )
            items = all_items[offset : offset + limit]
            return {
                "items": items,
                "total": len(all_items),
                "totalCaptured": jobs_repo.count(),
                "totalEligible": total_eligible,
                "totalNeedsReview": total_needs_review,
                "totalFiltered": total_filtered,
                "offset": offset,
                "limit": limit,
            }

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        """Return one draft projection."""

        with self.database.session() as session:
            draft = DraftRepository(session).get(draft_id)
            if draft is None:
                raise ValueError(f"draft not found: {draft_id}")
            return self._draft_dict(draft)

    def update_draft(self, *, draft_id: str, content: str) -> dict[str, Any]:
        """Edit a draft; editing an approved draft revokes its approval."""

        normalized = content.strip()
        if not normalized:
            raise ValueError("draft content cannot be empty")
        validation = validate_letter(normalized)
        with self.database.session() as session:
            draft = DraftRepository(session).get(draft_id)
            if draft is None:
                raise ValueError(f"draft not found: {draft_id}")
            previous_state = draft.review_state
            draft.content = normalized
            draft.validation_ok = validation.ok
            draft.validation_reasons_json = validation.reasons
            draft.revision += 1
            draft.review_state = ReviewState.PENDING.value
            draft.approved_at = None
            draft.updated_at = utc_now()
            AuditEventRepository(session).record(
                "draft_edited",
                job_id=draft.job_id,
                profile_id=draft.profile_id,
                payload={
                    "draft_id": draft.id,
                    "revision": draft.revision,
                    "approval_revoked": previous_state == ReviewState.APPROVED.value,
                    "validation_ok": validation.ok,
                },
            )
            session.flush()
            return self._draft_dict(draft)

    def decide(self, *, draft_id: str, decision: str) -> dict[str, Any]:
        """Approve or reject a draft after validating the requested transition."""

        try:
            parsed = ReviewDecision(decision)
        except ValueError as exc:
            raise ValueError(f"unsupported review decision: {decision}") from exc
        with self.database.session() as session:
            draft = DraftRepository(session).get(draft_id)
            if draft is None:
                raise ValueError(f"draft not found: {draft_id}")
            application = None
            if parsed is ReviewDecision.APPROVE:
                if not draft.validation_ok:
                    raise ValueError("draft must pass validation before approval")
                draft.review_state = ReviewState.APPROVED.value
                draft.approved_at = utc_now()
                event_type = "draft_approved"
                # 批准 = 这条触达进入投递流程。开一条 applications 记录（preparing），
                # 但**不代表已发送**——发送仍然是人在 BOSS 里手点，见红线 1。
                application = self._ensure_application(session, draft)
            else:
                draft.review_state = ReviewState.REJECTED.value
                draft.approved_at = None
                event_type = "draft_rejected"
            draft.updated_at = utc_now()
            AuditEventRepository(session).record(
                event_type,
                job_id=draft.job_id,
                profile_id=draft.profile_id,
                payload={
                    "draft_id": draft.id,
                    "revision": draft.revision,
                    **({"application_id": application.id} if application is not None else {}),
                },
            )
            session.flush()
            result = self._draft_dict(draft)
            if application is not None:
                result["applicationId"] = application.id
                result["applicationStatus"] = application.status
            return result

    @staticmethod
    def _ensure_application(session, draft):
        """批准草稿时保证有且只有一条 applications 记录（重复批准不新开）。"""

        applications = ApplicationRepository(session)
        existing = applications.for_job(draft.job_id)
        if existing is not None:
            if existing.draft_id is None:
                existing.draft_id = draft.id
            return existing
        application = applications.create(
            job_id=draft.job_id,
            profile_id=draft.profile_id,
            draft_id=draft.id,
            channel=ApplicationChannel.BOSS_CHAT.value,
            status=ApplicationStatus.PREPARING.value,
            note="审核台批准草稿",
        )
        AuditEventRepository(session).record(
            "application_created",
            job_id=draft.job_id,
            profile_id=draft.profile_id,
            payload={
                "application_id": application.id,
                "channel": application.channel,
                "status": application.status,
                "draft_id": draft.id,
            },
        )
        return application

    @staticmethod
    def _draft_dict(draft) -> dict[str, Any]:
        return {
            "id": draft.id,
            "content": draft.content,
            "originalContent": draft.original_content,
            "validationOk": draft.validation_ok,
            "validationReasons": draft.validation_reasons_json,
            "reviewState": draft.review_state,
            "revision": draft.revision,
            "approvedAt": draft.approved_at.isoformat() if draft.approved_at else None,
            "updatedAt": draft.updated_at.isoformat(),
        }

    @staticmethod
    def _filter_config(preference) -> JobFilterConfig:
        if preference is None:
            return JobFilterConfig()
        return JobFilterConfig(
            target_cities=tuple(preference.target_cities_json),
            target_roles=tuple(preference.target_roles_json),
            employment_types=tuple(preference.employment_types_json),
            title_excludes=tuple(preference.title_excludes_json),
            content_excludes=tuple(preference.content_excludes_json),
        )

    @staticmethod
    def _rule_match_dict(rule_match: RuleMatch) -> dict[str, Any]:
        return {
            "state": rule_match.state.value,
            "reasons": list(rule_match.reasons),
            "matchedCity": rule_match.matched_city,
            "matchedRole": rule_match.matched_role,
            "matchedEmploymentType": rule_match.matched_employment_type,
        }
