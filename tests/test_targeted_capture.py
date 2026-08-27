"""Multi-city targeted capture tests."""

from __future__ import annotations

import asyncio

from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.platform.boss import targeted_capture
from boss_zhipin.platform.boss.targeted_capture import (
    BossTargetedJobSource,
    build_search_routes,
)
from boss_zhipin.website_oper import finding_jobs


def test_build_search_routes_uses_supported_city_codes_and_encoded_queries():
    routes = build_search_routes(["北京", "深圳"], ["AI产品经理", "策略 产品"])
    assert len(routes) == 4
    assert "city=101010100" in routes[0].url
    assert "query=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86" in routes[0].url
    assert "city=101280600" in routes[2].url
    assert "%E7%AD%96%E7%95%A5+%E4%BA%A7%E5%93%81" in routes[3].url


def test_build_search_routes_rejects_unknown_city():
    try:
        build_search_routes(["杭州"], ["产品经理"])
    except ValueError as exc:
        assert "unsupported BOSS city" in str(exc)
    else:
        raise AssertionError("unknown cities must be rejected")


def test_targeted_source_navigates_routes_and_deduplicates(monkeypatch):
    calls: list[tuple] = []
    route_batches = iter(
        [
            (
                JobSnapshot(title="AI PM", description="JD", external_id="one"),
                JobSnapshot(title="Strategy PM", description="JD", external_id="two"),
            ),
            (
                JobSnapshot(title="AI PM", description="JD", external_id="one"),
                JobSnapshot(title="Product PM", description="JD", external_id="three"),
            ),
        ]
    )

    async def open_browser(url: str, browser: str):
        calls.append(("open", url, browser))

    async def login():
        calls.append(("login",))

    async def navigate(url: str):
        calls.append(("navigate", url))

    async def ready(timeout: float):
        calls.append(("ready", timeout))
        return True

    async def capture_feed(limit: int):
        calls.append(("capture", limit))
        return next(route_batches)

    monkeypatch.setattr(finding_jobs, "open_browser_with_options", open_browser)
    monkeypatch.setattr(finding_jobs, "log_in", login)
    monkeypatch.setattr(finding_jobs, "navigate_to_url", navigate)
    monkeypatch.setattr(finding_jobs, "wait_for_real_job_cards", ready)
    monkeypatch.setattr(targeted_capture, "_capture_current_feed", capture_feed)

    routes = build_search_routes(["北京", "上海"], ["AI产品经理"])
    jobs = asyncio.run(BossTargetedJobSource(routes, per_route_limit=2).capture_jobs(4))

    assert [job.external_id for job in jobs] == ["one", "two", "three"]
    assert calls[0][0] == "open"
    assert calls[1] == ("login",)
    assert [call[0] for call in calls].count("navigate") == 2
    assert [call for call in calls if call[0] == "capture"] == [
        ("capture", 2),
        ("capture", 2),
    ]
