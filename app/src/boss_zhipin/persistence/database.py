"""Database lifecycle and transaction helpers."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from boss_zhipin.persistence.migrations import MIGRATIONS, run_migrations


def default_database_path() -> Path:
    """Return the configured database path, defaulting to ``./data/reachout.db``."""

    configured = os.environ.get("BOSS_DATABASE_PATH", "").strip()
    return Path(configured) if configured else Path("data/reachout.db")


def _configure_sqlite(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


class Database:
    """Own the SQLite engine, migrations and short-lived ORM sessions."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite+pysqlite:///{self.path}",
            connect_args={"check_same_thread": False},
        )
        event.listen(self.engine, "connect", _configure_sqlite)
        self._session_factory = sessionmaker(
            bind=self.engine, class_=Session, expire_on_commit=False
        )

    def initialize(self) -> tuple[int, ...]:
        return run_migrations(self.engine)

    def pending_migrations(self) -> tuple[int, ...]:
        """未应用的迁移版本号。只读命令用它来「检查而不改库」。"""

        with self.engine.connect() as connection:
            exists = connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
            ).first()
            applied: set[int] = set()
            if exists is not None:
                applied = {
                    int(row[0])
                    for row in connection.execute(text("SELECT version FROM schema_migrations"))
                }
        return tuple(m.version for m in MIGRATIONS if m.version not in applied)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        self.engine.dispose()
