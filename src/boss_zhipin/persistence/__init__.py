"""SQLite persistence for captured jobs and workflow state."""

from boss_zhipin.persistence.database import Database, default_database_path

__all__ = ["Database", "default_database_path"]
