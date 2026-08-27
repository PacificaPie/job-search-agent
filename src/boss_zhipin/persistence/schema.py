"""SQLAlchemy schema for the first local-first database migration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class UtcDateTime(TypeDecorator[datetime]):
    """Persist UTC in SQLite and restore timezone-aware values on read."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    resume_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    search_label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    min_match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    min_keyword_match: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    exclude_keywords_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class ProfilePreferenceRow(Base):
    """Versioned personal targeting rules kept separate from the v1 profile table."""

    __tablename__ = "profile_preferences"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    target_cities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    target_roles_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    employment_types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    title_excludes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    content_excludes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    min_match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    daily_outreach_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    fixed_greeting: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_jobs_canonical_key"),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="boss_zhipin")
    external_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    canonical_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    company: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    salary: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    availability: Mapped[str] = mapped_column(String(30), nullable=False, default="available")
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)

    audit_events: Mapped[list[AuditEventRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class EvaluationRow(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_job_created_at", "job_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    keyword_matches_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    keyword_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)


class DraftRow(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        Index("ix_drafts_job_updated_at", "job_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    validation_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    review_state: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)

    job: Mapped[JobRow | None] = relationship(back_populates="audit_events")
