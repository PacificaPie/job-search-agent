"""Capture LinkedIn jobs through the local, unofficial linkedin-cli project."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from boss_zhipin.domain.models import JobSnapshot

log = logging.getLogger(__name__)

DEFAULT_LOCATIONS = (
    "New York, New York, United States",
    "San Francisco, California, United States",
    "Boston, Massachusetts, United States",
    "Washington, District of Columbia, United States",
    "Austin, Texas, United States",
)
DEFAULT_QUERIES = (
    "AI Product Manager",
    "Generative AI Product Manager",
    "AI/ML Product Manager",
    "Product Strategy",
)


class JsonCommandRunner(Protocol):
    async def run_json(self, arguments: list[str]) -> Any: ...


class LinkedInCliRunner:
    """Run the sibling CLI with JSON-only stdout and actionable failures."""

    def __init__(self, project_path: str | Path | None = None, *, timeout: float = 180) -> None:
        configured = os.getenv("LINKEDIN_CLI_PROJECT", "").strip()
        self.project_path = Path(project_path or configured or "../linkedin-cli-frizynn").resolve()
        self.timeout = timeout

    async def run_json(self, arguments: list[str]) -> Any:
        if not (self.project_path / "pyproject.toml").is_file():
            raise RuntimeError(f"LinkedIn CLI project not found: {self.project_path}")
        process = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "--project",
            str(self.project_path),
            "linkedin",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("LinkedIn CLI timed out") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"LinkedIn CLI failed: {detail or process.returncode}")
        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("LinkedIn CLI returned invalid JSON") from exc


@dataclass(frozen=True, slots=True)
class LinkedInSearchRoute:
    location: str
    query: str


def build_search_routes(
    locations: tuple[str, ...] = DEFAULT_LOCATIONS,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
) -> tuple[LinkedInSearchRoute, ...]:
    """Build a deterministic location-by-query search plan."""
    routes = tuple(
        LinkedInSearchRoute(location.strip(), query.strip())
        for location in locations
        for query in queries
        if location.strip() and query.strip()
    )
    if not routes:
        raise ValueError("LinkedIn search requires locations and queries")
    return routes


def snapshot_from_cli_job(summary: dict[str, Any], detail: dict[str, Any]) -> JobSnapshot:
    """Map stable linkedin-cli JSON into the shared local job model."""
    job_id = str(detail.get("job_id") or summary.get("job_id") or "").strip()
    title = str(detail.get("title") or summary.get("title") or "").strip()
    description = str(detail.get("description") or "").strip()
    return JobSnapshot(
        platform="linkedin",
        external_id=job_id or None,
        title=title,
        company=str(detail.get("company") or summary.get("company") or "").strip(),
        location=str(detail.get("location") or summary.get("location") or "").strip(),
        description=description,
        source_url=str(
            detail.get("url")
            or summary.get("url")
            or (f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else "")
        ).strip()
        or None,
        raw_payload={"search": summary, "detail": detail},
    )


class LinkedInCliJobSource:
    """Sequentially search and fetch full LinkedIn jobs without sending anything."""

    def __init__(
        self,
        runner: JsonCommandRunner,
        routes: tuple[LinkedInSearchRoute, ...],
        *,
        per_route_limit: int = 3,
    ) -> None:
        if per_route_limit < 1:
            raise ValueError("per-route limit must be at least 1")
        if not routes:
            raise ValueError("LinkedIn routes cannot be empty")
        self.runner = runner
        self.routes = routes
        self.per_route_limit = per_route_limit

    async def capture_jobs(self, limit: int) -> tuple[JobSnapshot, ...]:
        if limit < 1:
            raise ValueError("capture limit must be at least 1")
        snapshots: list[JobSnapshot] = []
        seen_ids: set[str] = set()
        for route in self.routes:
            if len(snapshots) >= limit:
                break
            results = await self.runner.run_json(
                [
                    "jobs",
                    "search",
                    route.query,
                    "--location",
                    route.location,
                    "--max",
                    str(min(self.per_route_limit, limit - len(snapshots))),
                    "--date-posted",
                    "pastWeek",
                    "--experience",
                    "entryLevel",
                    "--experience",
                    "associate",
                    "--employment-type",
                    "fullTime",
                    "--json",
                ]
            )
            if not isinstance(results, list):
                raise RuntimeError("LinkedIn jobs search returned a non-list payload")
            for summary in results:
                if len(snapshots) >= limit:
                    break
                if not isinstance(summary, dict):
                    continue
                job_id = str(summary.get("job_id") or "").strip()
                if not job_id or job_id in seen_ids:
                    continue
                detail = await self.runner.run_json(["jobs", "fetch", job_id, "--json"])
                if not isinstance(detail, dict):
                    log.warning("LinkedIn job detail is not an object: %s", job_id)
                    continue
                snapshot = snapshot_from_cli_job(summary, detail)
                if not snapshot.title and not snapshot.description:
                    continue
                seen_ids.add(job_id)
                snapshots.append(snapshot)
        return tuple(snapshots)

