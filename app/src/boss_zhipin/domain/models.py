"""Framework-independent domain values for the local-first workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """A structured view of one job as observed in the current browser feed.

    ``external_id`` and ``source_url`` are optional because BOSS does not expose
    them consistently on every feed variant.  At least a title or description
    is required so the snapshot can be identified without inventing data.
    """

    title: str
    platform: str = "boss_zhipin"
    company: str = ""
    location: str = ""
    salary: str = ""
    description: str = ""
    external_id: str | None = None
    source_url: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip() and not self.description.strip():
            raise ValueError("job snapshot requires a title or description")
        if not self.platform.strip():
            raise ValueError("job snapshot requires a platform")


@dataclass(frozen=True, slots=True)
class CaptureSummary:
    """Result of one capture-only batch."""

    observed: int
    created: int
    updated: int
    job_ids: tuple[str, ...]
