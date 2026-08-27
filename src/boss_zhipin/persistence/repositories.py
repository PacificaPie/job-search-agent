"""Repository operations used by application services."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from boss_zhipin.domain.job_identity import canonical_job_key
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.persistence.schema import (
    AuditEventRow,
    DraftRow,
    EvaluationRow,
    JobRow,
    ProfilePreferenceRow,
    ProfileRow,
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
