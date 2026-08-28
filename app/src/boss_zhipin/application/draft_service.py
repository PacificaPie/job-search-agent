"""Generate and validate outreach drafts; this service never sends them."""

from __future__ import annotations

from collections.abc import Callable

from boss_zhipin.audit import validate_letter
from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    AuditEventRepository,
    DraftRepository,
    JobRepository,
    ProfileRepository,
)

DraftGenerator = Callable[[str], str]


class DraftService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def generate(
        self,
        *,
        job_id: str,
        profile_id: str,
        generator: DraftGenerator,
    ) -> str:
        """Generate a new pending draft and return its id."""

        with self.database.session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                raise ValueError(f"job not found: {job_id}")
            if ProfileRepository(session).get(profile_id) is None:
                raise ValueError(f"profile not found: {profile_id}")
            description = job.description

        # Generation may call a remote LLM and must not hold a DB transaction.
        content = generator(description).strip()
        validation = validate_letter(content)
        with self.database.session() as session:
            if JobRepository(session).get(job_id) is None:
                raise ValueError(f"job not found: {job_id}")
            if ProfileRepository(session).get(profile_id) is None:
                raise ValueError(f"profile not found: {profile_id}")
            draft = DraftRepository(session).create(
                job_id=job_id,
                profile_id=profile_id,
                content=content,
                validation_ok=validation.ok,
                validation_reasons=validation.reasons,
            )
            AuditEventRepository(session).record(
                "draft_generated",
                job_id=job_id,
                profile_id=profile_id,
                payload={
                    "draft_id": draft.id,
                    "validation_ok": validation.ok,
                    "validation_reasons": validation.reasons,
                },
            )
            return draft.id
