"""Small explicit migration runner for the embedded SQLite database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from boss_zhipin.persistence.schema import (
    AuditEventRow,
    DraftRow,
    EvaluationRow,
    JobRow,
    ProfilePreferenceRow,
    ProfileRow,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def _create_initial_schema(connection: Connection) -> None:
    # Keep migration 1 stable as new ORM tables are added in later versions.
    ProfileRow.__table__.create(connection, checkfirst=True)
    JobRow.__table__.create(connection, checkfirst=True)
    AuditEventRow.__table__.create(connection, checkfirst=True)


def _create_review_schema(connection: Connection) -> None:
    EvaluationRow.__table__.create(connection, checkfirst=True)
    DraftRow.__table__.create(connection, checkfirst=True)


def _create_profile_preferences(connection: Connection) -> None:
    ProfilePreferenceRow.__table__.create(connection, checkfirst=True)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial local-first schema", _create_initial_schema),
    Migration(2, "evaluation and human review schema", _create_review_schema),
    Migration(3, "personal job targeting preferences", _create_profile_preferences),
)


def run_migrations(engine: Engine) -> tuple[int, ...]:
    """Apply missing migrations in order and return applied versions."""

    applied: list[int] = []
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        existing = {
            int(row[0])
            for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }
        for migration in MIGRATIONS:
            if migration.version in existing:
                continue
            migration.apply(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version, name) VALUES (:version, :name)"),
                {"version": migration.version, "name": migration.name},
            )
            applied.append(migration.version)
    return tuple(applied)
