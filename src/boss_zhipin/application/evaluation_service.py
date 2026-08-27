"""Persist reproducible job evaluations without coupling them to the UI."""

from __future__ import annotations

from typing import Any, Callable

from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    AuditEventRepository,
    EvaluationRepository,
    JobRepository,
    ProfileRepository,
)

Evaluator = Callable[[str], dict[str, Any]]


class EvaluationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def evaluate(
        self,
        *,
        job_id: str,
        profile_id: str,
        evaluator: Evaluator,
        model: str = "",
    ) -> str:
        """Evaluate one persisted job and return the new evaluation id."""

        with self.database.session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                raise ValueError(f"job not found: {job_id}")
            if ProfileRepository(session).get(profile_id) is None:
                raise ValueError(f"profile not found: {profile_id}")
            description = job.description

        # LLM/network work must not hold an SQLite transaction open.
        details = evaluator(description)
        with self.database.session() as session:
            if JobRepository(session).get(job_id) is None:
                raise ValueError(f"job not found: {job_id}")
            if ProfileRepository(session).get(profile_id) is None:
                raise ValueError(f"profile not found: {profile_id}")
            score = details.get("score")
            evaluation = EvaluationRepository(session).create(
                job_id=job_id,
                profile_id=profile_id,
                keyword_matches=list(details.get("matched_keywords") or []),
                keyword_passed=details.get("stage") != "keyword",
                score=int(score) if score is not None else None,
                reason=str(details.get("reason") or ""),
                degraded=bool(details.get("scoring_degraded", False)),
                model=model,
            )
            AuditEventRepository(session).record(
                "job_evaluated",
                job_id=job_id,
                profile_id=profile_id,
                payload={"evaluation_id": evaluation.id, "score": evaluation.score},
            )
            return evaluation.id
