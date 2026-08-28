"""Application (投递) tracking: 状态机流转 + 审计留痕。

这张表是蓝图第 4 节说的「唯一不可作弊的指标来源」：回调率 = first_response_at
非空的比例，各阶段转化率从 status_history 里数。所以这里的原则是：

- 状态只能按 ``domain.application_status`` 的白名单流转，非法流转直接抛；
- 每次流转都往 ``status_history_json`` 追加一条，**从不覆盖**；
- 每次流转都写一条 audit_event，跟 draft 审批用同一套审计通道。

红线：这里不做任何"自动提交"。``submitted`` 只能由人在审核台点出来，
service 只负责记录人已经做过的事。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boss_zhipin.domain.application_status import (
    ApplicationChannel,
    ApplicationStatus,
    allowed_transitions,
    ensure_transition,
    is_valid_status,
)
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    ApplicationRepository,
    AuditEventRepository,
    DraftRepository,
    JobRepository,
)
from boss_zhipin.persistence.schema import utc_now

#: 进入这些状态即视为「对方有过回应」，用来算回调率。
_RESPONDED_STATUSES = frozenset(
    {ApplicationStatus.SCREENING.value, ApplicationStatus.OFFER.value}
)


def _is_response(status: str) -> bool:
    return status in _RESPONDED_STATUSES or status.startswith("interview_")


class ApplicationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        job_id: str,
        profile_id: str | None = None,
        draft_id: str | None = None,
        resume_version_id: str | None = None,
        channel: str = ApplicationChannel.BOSS_CHAT.value,
        note: str = "",
    ) -> dict[str, Any]:
        """为一个岗位开一条投递记录（幂等：已有则原样返回）。"""

        if channel not in set(ApplicationChannel):
            raise ValueError(f"unsupported application channel: {channel}")
        with self.database.session() as session:
            if JobRepository(session).get(job_id) is None:
                raise ValueError(f"job not found: {job_id}")
            applications = ApplicationRepository(session)
            existing = applications.for_job(job_id)
            if existing is not None:
                return self._to_dict(existing)
            application = applications.create(
                job_id=job_id,
                profile_id=profile_id,
                draft_id=draft_id,
                resume_version_id=resume_version_id,
                channel=channel,
                status=ApplicationStatus.PREPARING.value,
                note=note,
            )
            AuditEventRepository(session).record(
                "application_created",
                job_id=job_id,
                profile_id=profile_id,
                payload={
                    "application_id": application.id,
                    "channel": channel,
                    "status": application.status,
                    "draft_id": draft_id,
                },
            )
            session.flush()
            return self._to_dict(application)

    def advance(
        self,
        *,
        application_id: str,
        status: str,
        note: str = "",
        next_action: str | None = None,
        next_action_due: datetime | None = None,
    ) -> dict[str, Any]:
        """流转到下一个状态。非法流转抛 ValueError，不写任何东西。"""

        with self.database.session() as session:
            applications = ApplicationRepository(session)
            application = applications.get(application_id)
            if application is None:
                raise ValueError(f"application not found: {application_id}")
            previous = application.status
            ensure_transition(previous, status)

            application.status = status
            applications.append_history(application, status=status, note=note)
            if status == ApplicationStatus.SUBMITTED.value and application.submitted_at is None:
                application.submitted_at = utc_now()
            if _is_response(status) and application.first_response_at is None:
                application.first_response_at = utc_now()
            if next_action is not None:
                application.next_action = next_action
            if next_action_due is not None:
                application.next_action_due = next_action_due
            application.updated_at = utc_now()

            AuditEventRepository(session).record(
                "application_status_changed",
                job_id=application.job_id,
                profile_id=application.profile_id,
                payload={
                    "application_id": application.id,
                    "from": previous,
                    "to": status,
                    "note": note,
                },
            )
            session.flush()
            return self._to_dict(application)

    def get_for_job(self, job_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            application = ApplicationRepository(session).for_job(job_id)
            return None if application is None else self._to_dict(application)

    def list(
        self, *, statuses: tuple[str, ...] = (), offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset cannot be negative")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        for status in statuses:
            if not is_valid_status(status):
                raise ValueError(f"unknown application status: {status}")
        with self.database.session() as session:
            applications = ApplicationRepository(session)
            rows = applications.list_by_status(statuses=statuses, offset=offset, limit=limit)
            drafts = DraftRepository(session)
            jobs = JobRepository(session)
            items = []
            for row in rows:
                job = jobs.get(row.job_id)
                draft = drafts.get(row.draft_id) if row.draft_id else None
                items.append(
                    {
                        **self._to_dict(row),
                        "job": None if job is None else {
                            "id": job.id,
                            "platform": job.platform,
                            "title": job.title,
                            "company": job.company,
                            "location": job.location,
                        },
                        "draftContent": None if draft is None else draft.content,
                    }
                )
            return {
                "items": items,
                "countsByStatus": applications.count_by_status(),
                "offset": offset,
                "limit": limit,
            }

    @staticmethod
    def _to_dict(application) -> dict[str, Any]:
        return {
            "id": application.id,
            "jobId": application.job_id,
            "profileId": application.profile_id,
            "draftId": application.draft_id,
            "resumeVersionId": application.resume_version_id,
            "channel": application.channel,
            "status": application.status,
            "statusHistory": application.status_history_json,
            "allowedTransitions": sorted(allowed_transitions(application.status)),
            "submittedAt": application.submitted_at.isoformat()
            if application.submitted_at
            else None,
            "firstResponseAt": application.first_response_at.isoformat()
            if application.first_response_at
            else None,
            "nextAction": application.next_action,
            "nextActionDue": application.next_action_due.isoformat()
            if application.next_action_due
            else None,
            "notes": application.notes,
            "createdAt": application.created_at.isoformat(),
            "updatedAt": application.updated_at.isoformat(),
        }
