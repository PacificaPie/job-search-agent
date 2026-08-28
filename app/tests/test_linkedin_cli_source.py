"""Free local LinkedIn CLI adapter tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from boss_zhipin.platform.linkedin.cli_source import (
    LinkedInCliJobSource,
    LinkedInCliRunner,
    build_search_routes,
    snapshot_from_cli_job,
)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def run_json(self, arguments: list[str]):
        self.calls.append(arguments)
        if arguments[:2] == ["jobs", "search"]:
            return [
                {
                    "job_id": "123",
                    "title": "AI Product Manager",
                    "company": "Example AI",
                    "location": "New York, NY",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                }
            ]
        return {
            "job_id": arguments[2],
            "title": "AI Product Manager",
            "company": "Example AI",
            "location": "New York, NY",
            "description": "2027 new grad. Visa sponsorship is available.",
            "url": "https://www.linkedin.com/jobs/view/123/",
        }


def test_build_search_routes_is_location_by_query():
    routes = build_search_routes(("New York", "Austin"), ("AI PM", "Product Strategy"))
    assert len(routes) == 4
    assert routes[0].location == "New York"
    assert routes[-1].query == "Product Strategy"


def test_snapshot_mapping_sets_linkedin_platform():
    snapshot = snapshot_from_cli_job(
        {"job_id": "123", "title": "AI PM"},
        {"job_id": "123", "description": "2027 new grad; sponsorship available"},
    )
    assert snapshot.platform == "linkedin"
    assert snapshot.external_id == "123"
    assert snapshot.source_url == "https://www.linkedin.com/jobs/view/123/"


def test_source_searches_then_fetches_full_details():
    runner = FakeRunner()
    source = LinkedInCliJobSource(
        runner,
        build_search_routes(("New York",), ("AI Product Manager",)),
        per_route_limit=3,
    )
    snapshots = asyncio.run(source.capture_jobs(5))
    assert len(snapshots) == 1
    assert "sponsorship" in snapshots[0].description
    assert runner.calls[0][:3] == ["jobs", "search", "AI Product Manager"]
    assert runner.calls[1] == ["jobs", "fetch", "123", "--json"]


def test_runner_rejects_missing_project(tmp_path: Path):
    runner = LinkedInCliRunner(tmp_path / "missing")
    try:
        asyncio.run(runner.run_json(["jobs", "search"]))
    except RuntimeError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing project should fail")
