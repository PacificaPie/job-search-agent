"""Manage one active profile's local job-targeting preferences."""

from __future__ import annotations

from typing import Any

from boss_zhipin.persistence.database import Database
from boss_zhipin.persistence.repositories import (
    AuditEventRepository,
    ProfilePreferenceRepository,
    ProfileRepository,
)


class TargetingService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def configure_active(
        self,
        *,
        target_cities: list[str],
        target_roles: list[str],
        employment_types: list[str],
        title_excludes: list[str],
        content_excludes: list[str],
        min_match_score: int,
        daily_outreach_limit: int,
        fixed_greeting: str,
    ) -> dict[str, Any]:
        """Persist targeting rules for the active profile."""

        with self.database.session() as session:
            profile = ProfileRepository(session).get_active()
            if profile is None:
                raise ValueError("active profile not found; capture jobs first")
            preference = ProfilePreferenceRepository(session).upsert(
                profile_id=profile.id,
                target_cities=target_cities,
                target_roles=target_roles,
                employment_types=employment_types,
                title_excludes=title_excludes,
                content_excludes=content_excludes,
                min_match_score=min_match_score,
                daily_outreach_limit=daily_outreach_limit,
                fixed_greeting=fixed_greeting,
            )
            profile.min_match_score = min_match_score
            AuditEventRepository(session).record(
                "targeting_preferences_updated",
                profile_id=profile.id,
                payload={
                    "target_cities": preference.target_cities_json,
                    "target_roles": preference.target_roles_json,
                    "employment_types": preference.employment_types_json,
                    "min_match_score": preference.min_match_score,
                    "daily_outreach_limit": preference.daily_outreach_limit,
                },
            )
            return self._as_dict(preference)

    def get_active(self) -> dict[str, Any] | None:
        """Return active targeting preferences, if configured."""

        with self.database.session() as session:
            profile = ProfileRepository(session).get_active()
            if profile is None:
                return None
            preference = ProfilePreferenceRepository(session).get(profile.id)
            return None if preference is None else self._as_dict(preference)

    @staticmethod
    def _as_dict(preference) -> dict[str, Any]:
        return {
            "profileId": preference.profile_id,
            "targetCities": preference.target_cities_json,
            "targetRoles": preference.target_roles_json,
            "employmentTypes": preference.employment_types_json,
            "titleExcludes": preference.title_excludes_json,
            "contentExcludes": preference.content_excludes_json,
            "minMatchScore": preference.min_match_score,
            "dailyOutreachLimit": preference.daily_outreach_limit,
            "fixedGreeting": preference.fixed_greeting,
            "updatedAt": preference.updated_at.isoformat(),
        }
