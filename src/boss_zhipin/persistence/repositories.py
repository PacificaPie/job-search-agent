"""Repository operations used by application services."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boss_zhipin.domain.campaign import ActionStrategy
from boss_zhipin.domain.job_identity import canonical_job_key
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.schema import (
    ApplicationRow,
    AuditEventRow,
    DraftRow,
    EvaluationRow,
    JobCampaignMatchRow,
    JobRow,
    ProfilePreferenceRow,
    ProfileRow,
    ResumeVersionRow,
    SearchCampaignRow,
    utc_now,
)


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str,
        display_name: str = "",
        resume_path: str = "",
        search_label: str = "",
    ) -> ProfileRow:
        profile = ProfileRow(
            name=name,
            display_name=display_name,
            resume_path=resume_path,
            search_label=search_label,
        )
        self.session.add(profile)
        self.session.flush()
        return profile

    def get(self, profile_id: str) -> ProfileRow | None:
        return self.session.get(ProfileRow, profile_id)

    def get_active(self) -> ProfileRow | None:
        return self.session.scalar(
            select(ProfileRow)
            .where(ProfileRow.is_active.is_(True))
            .order_by(ProfileRow.created_at)
            .limit(1)
        )


class ProfilePreferenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, profile_id: str) -> ProfilePreferenceRow | None:
        return self.session.get(ProfilePreferenceRow, profile_id)

    def upsert(
        self,
        *,
        profile_id: str,
        target_cities: list[str],
        target_roles: list[str],
        employment_types: list[str],
        title_excludes: list[str],
        content_excludes: list[str],
        min_match_score: int,
        daily_outreach_limit: int,
        fixed_greeting: str,
    ) -> ProfilePreferenceRow:
        if not 0 <= min_match_score <= 100:
            raise ValueError("min match score must be between 0 and 100")
        if not 1 <= daily_outreach_limit <= 100:
            raise ValueError("daily outreach limit must be between 1 and 100")
        preference = self.get(profile_id)
        if preference is None:
            preference = ProfilePreferenceRow(profile_id=profile_id)
            self.session.add(preference)
        preference.target_cities_json = _clean_string_list(target_cities)
        preference.target_roles_json = _clean_string_list(target_roles)
        preference.employment_types_json = _clean_string_list(employment_types)
        preference.title_excludes_json = _clean_string_list(title_excludes)
        preference.content_excludes_json = _clean_string_list(content_excludes)
        preference.min_match_score = min_match_score
        preference.daily_outreach_limit = daily_outreach_limit
        preference.fixed_greeting = fixed_greeting.strip()
        preference.updated_at = utc_now()
        self.session.flush()
        return preference


def _clean_string_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


_CAMPAIGN_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SearchCampaignRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, campaign_id: str) -> SearchCampaignRow | None:
        return self.session.get(SearchCampaignRow, campaign_id)

    def get_by_key(self, *, profile_id: str, campaign_key: str) -> SearchCampaignRow | None:
        return self.session.scalar(
            select(SearchCampaignRow).where(
                SearchCampaignRow.profile_id == profile_id,
                SearchCampaignRow.campaign_key == campaign_key,
            )
        )

    def list_active(self, *, profile_id: str) -> list[SearchCampaignRow]:
        return list(
            self.session.scalars(
                select(SearchCampaignRow)
                .where(
                    SearchCampaignRow.profile_id == profile_id,
                    SearchCampaignRow.is_active.is_(True),
                )
                .order_by(SearchCampaignRow.created_at, SearchCampaignRow.id)
            )
        )

    def upsert(
        self,
        *,
        profile_id: str,
        campaign_key: str,
        name: str,
        source_platforms: list[str],
        targeting_config: dict[str, Any],
        action_strategy: str,
        is_active: bool = True,
    ) -> SearchCampaignRow:
        normalized_key = campaign_key.strip()
        normalized_name = name.strip()
        platforms = _clean_string_list(source_platforms)
        if not _CAMPAIGN_KEY_RE.fullmatch(normalized_key):
            raise ValueError("campaign key must be a lowercase kebab-case identifier")
        if not normalized_name:
            raise ValueError("campaign name cannot be empty")
        if not platforms:
            raise ValueError("campaign requires at least one source platform")
        try:
            strategy = ActionStrategy(action_strategy)
        except ValueError as exc:
            raise ValueError(f"unsupported campaign action strategy: {action_strategy}") from exc

        campaign = self.get_by_key(profile_id=profile_id, campaign_key=normalized_key)
        if campaign is None:
            campaign = SearchCampaignRow(
                profile_id=profile_id,
                campaign_key=normalized_key,
                name=normalized_name,
                source_platforms_json=platforms,
                targeting_config_json=dict(targeting_config),
                action_strategy=strategy.value,
                is_active=is_active,
            )
            self.session.add(campaign)
        else:
            campaign.name = normalized_name
            campaign.source_platforms_json = platforms
            campaign.targeting_config_json = dict(targeting_config)
            campaign.action_strategy = strategy.value
            campaign.is_active = is_active
            campaign.updated_at = utc_now()
        self.session.flush()
        return campaign


class JobCampaignMatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, *, campaign_id: str, job_id: str) -> JobCampaignMatchRow | None:
        return self.session.get(JobCampaignMatchRow, (campaign_id, job_id))

    def observe(
        self,
        *,
        campaign_id: str,
        job_id: str,
        source_route: str = "",
        discovery_metadata: dict[str, Any] | None = None,
        observed_at: datetime | None = None,
    ) -> JobCampaignMatchRow:
        now = observed_at or utc_now()
        match = self.get(campaign_id=campaign_id, job_id=job_id)
        if match is None:
            match = JobCampaignMatchRow(
                campaign_id=campaign_id,
                job_id=job_id,
                source_route=source_route.strip(),
                discovery_metadata_json=dict(discovery_metadata or {}),
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(match)
        else:
            if source_route.strip():
                match.source_route = source_route.strip()
            if discovery_metadata:
                match.discovery_metadata_json = dict(discovery_metadata)
            match.last_seen_at = now
        self.session.flush()
        return match

    def update_assessment(
        self,
        *,
        campaign_id: str,
        job_id: str,
        rule_state: str,
        rule_reasons: list[str],
        score: int | None = None,
        score_reason: str = "",
        evaluation_policy_version: str = "",
    ) -> JobCampaignMatchRow:
        if score is not None and not 0 <= score <= 100:
            raise ValueError("campaign match score must be between 0 and 100")
        match = self.get(campaign_id=campaign_id, job_id=job_id)
        if match is None:
            raise ValueError("job has not been observed in this campaign")
        match.rule_state = rule_state.strip()
        match.rule_reasons_json = _clean_string_list(rule_reasons)
        match.score = score
        match.score_reason = score_reason.strip()
        match.evaluation_policy_version = evaluation_policy_version.strip()
        self.session.flush()
        return match

    def list_for_campaign(
        self, *, campaign_id: str, offset: int = 0, limit: int = 100
    ) -> list[JobCampaignMatchRow]:
        return list(
            self.session.scalars(
                select(JobCampaignMatchRow)
                .where(JobCampaignMatchRow.campaign_id == campaign_id)
                .order_by(
                    JobCampaignMatchRow.last_seen_at.desc(),
                    JobCampaignMatchRow.job_id,
                )
                .offset(offset)
                .limit(limit)
            )
        )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: str) -> JobRow | None:
        return self.session.get(JobRow, job_id)

    def find_by_canonical_key(self, key: str) -> JobRow | None:
        return self.session.scalar(select(JobRow).where(JobRow.canonical_key == key))

    def list_recent(self, *, offset: int = 0, limit: int = 30) -> list[JobRow]:
        return list(
            self.session.scalars(
                select(JobRow)
                .order_by(JobRow.last_seen_at.desc(), JobRow.id)
                .offset(offset)
                .limit(limit)
            )
        )

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(JobRow)) or 0)

    def upsert_snapshot(
        self,
        snapshot: JobSnapshot,
        *,
        observed_at: datetime | None = None,
    ) -> tuple[JobRow, bool]:
        now = observed_at or utc_now()
        key = canonical_job_key(snapshot)
        job = self.find_by_canonical_key(key)
        if job is None:
            job = JobRow(
                platform=snapshot.platform.strip(),
                external_id=(snapshot.external_id or "").strip() or None,
                canonical_key=key,
                title=snapshot.title.strip(),
                company=snapshot.company.strip(),
                location=snapshot.location.strip(),
                salary=snapshot.salary.strip(),
                description=snapshot.description.strip(),
                source_url=(snapshot.source_url or "").strip() or None,
                raw_payload_json=dict(snapshot.raw_payload),
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(job)
            self.session.flush()
            return job, True

        for field_name in ("title", "company", "location", "salary", "description"):
            value = getattr(snapshot, field_name).strip()
            if value:
                setattr(job, field_name, value)
        job.platform = snapshot.platform.strip()
        if snapshot.external_id and snapshot.external_id.strip():
            job.external_id = snapshot.external_id.strip()
        if snapshot.source_url and snapshot.source_url.strip():
            job.source_url = snapshot.source_url.strip()
        if snapshot.raw_payload:
            job.raw_payload_json = dict(snapshot.raw_payload)
        job.last_seen_at = now
        self.session.flush()
        return job, False


class EvaluationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        job_id: str,
        profile_id: str,
        keyword_matches: list[str] | None = None,
        keyword_passed: bool = True,
        score: int | None = None,
        reason: str = "",
        degraded: bool = False,
        model: str = "",
        prompt_version: str = "v1",
    ) -> EvaluationRow:
        if score is not None and not 0 <= score <= 100:
            raise ValueError("evaluation score must be between 0 and 100")
        evaluation = EvaluationRow(
            job_id=job_id,
            profile_id=profile_id,
            keyword_matches_json=keyword_matches or [],
            keyword_passed=keyword_passed,
            score=score,
            reason=reason.strip(),
            degraded=degraded,
            model=model.strip(),
            prompt_version=prompt_version,
        )
        self.session.add(evaluation)
        self.session.flush()
        return evaluation

    def latest_for_job(self, job_id: str) -> EvaluationRow | None:
        return self.session.scalar(
            select(EvaluationRow)
            .where(EvaluationRow.job_id == job_id)
            .order_by(EvaluationRow.created_at.desc(), EvaluationRow.id.desc())
            .limit(1)
        )


class DraftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, draft_id: str) -> DraftRow | None:
        return self.session.get(DraftRow, draft_id)

    def latest_for_job(self, job_id: str) -> DraftRow | None:
        return self.session.scalar(
            select(DraftRow)
            .where(DraftRow.job_id == job_id)
            .order_by(DraftRow.created_at.desc(), DraftRow.id.desc())
            .limit(1)
        )

    def create(
        self,
        *,
        job_id: str,
        profile_id: str,
        content: str,
        validation_ok: bool,
        validation_reasons: list[str] | None = None,
    ) -> DraftRow:
        normalized = content.strip()
        if not normalized:
            raise ValueError("draft content cannot be empty")
        draft = DraftRow(
            job_id=job_id,
            profile_id=profile_id,
            content=normalized,
            original_content=normalized,
            validation_ok=validation_ok,
            validation_reasons_json=validation_reasons or [],
        )
        self.session.add(draft)
        self.session.flush()
        return draft


class ResumeVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, resume_version_id: str) -> ResumeVersionRow | None:
        return self.session.get(ResumeVersionRow, resume_version_id)

    def create(
        self,
        *,
        job_id: str | None = None,
        profile_id: str | None = None,
        archive_entry_ids: list[str] | None = None,
        lang: str = "zh",
        html_path: str = "",
        pdf_path: str = "",
    ) -> ResumeVersionRow:
        if lang not in {"zh", "en"}:
            raise ValueError(f"unsupported resume language: {lang}")
        version = ResumeVersionRow(
            job_id=job_id,
            profile_id=profile_id,
            archive_entry_ids_json=archive_entry_ids or [],
            lang=lang,
            html_path=html_path,
            pdf_path=pdf_path,
        )
        self.session.add(version)
        self.session.flush()
        return version

    def latest_for_job(self, job_id: str) -> ResumeVersionRow | None:
        return self.session.scalar(
            select(ResumeVersionRow)
            .where(ResumeVersionRow.job_id == job_id)
            .order_by(ResumeVersionRow.created_at.desc(), ResumeVersionRow.id.desc())
            .limit(1)
        )


class ApplicationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, application_id: str) -> ApplicationRow | None:
        return self.session.get(ApplicationRow, application_id)

    def for_job(self, job_id: str) -> ApplicationRow | None:
        """一个岗位只跟一条投递记录——重复批准同一个岗位不该产生第二条。"""

        return self.session.scalar(
            select(ApplicationRow)
            .where(ApplicationRow.job_id == job_id)
            .order_by(ApplicationRow.created_at.desc(), ApplicationRow.id.desc())
            .limit(1)
        )

    def create(
        self,
        *,
        job_id: str,
        profile_id: str | None = None,
        draft_id: str | None = None,
        resume_version_id: str | None = None,
        channel: str = "boss_chat",
        status: str = "preparing",
        note: str = "",
    ) -> ApplicationRow:
        application = ApplicationRow(
            job_id=job_id,
            profile_id=profile_id,
            draft_id=draft_id,
            resume_version_id=resume_version_id,
            channel=channel,
            status=status,
            status_history_json=[
                {"status": status, "at": utc_now().isoformat(), "note": note}
            ],
        )
        self.session.add(application)
        self.session.flush()
        return application

    def append_history(self, application: ApplicationRow, *, status: str, note: str = "") -> None:
        """JSON 列要整列重新赋值，原地 append 不会被 SQLAlchemy 标记为脏。"""

        application.status_history_json = [
            *application.status_history_json,
            {"status": status, "at": utc_now().isoformat(), "note": note},
        ]

    def list_by_status(
        self, *, statuses: tuple[str, ...] = (), offset: int = 0, limit: int = 50
    ) -> list[ApplicationRow]:
        query = select(ApplicationRow)
        if statuses:
            query = query.where(ApplicationRow.status.in_(statuses))
        query = query.order_by(ApplicationRow.updated_at.desc(), ApplicationRow.id.desc())
        return list(self.session.scalars(query.offset(offset).limit(limit)))

    def count_by_status(self) -> dict[str, int]:
        rows = self.session.execute(
            select(ApplicationRow.status, func.count()).group_by(ApplicationRow.status)
        )
        return {status: int(count) for status, count in rows}

class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        event_type: str,
        *,
        job_id: str | None = None,
        profile_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEventRow:
        event = AuditEventRow(
            job_id=job_id,
            profile_id=profile_id,
            event_type=event_type,
            payload_json=payload or {},
        )
        self.session.add(event)
        self.session.flush()
        return event
