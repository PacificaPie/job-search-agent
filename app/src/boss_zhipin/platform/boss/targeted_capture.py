"""Sequential multi-city BOSS search capture for the personal daily workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

from boss_zhipin.domain.job_identity import canonical_job_key
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.platform.boss.capture_source import _capture_current_feed
from boss_zhipin.website_oper import finding_jobs

log = logging.getLogger(__name__)

CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
}
SEARCH_URL = "https://www.zhipin.com/web/geek/jobs"


@dataclass(frozen=True, slots=True)
class SearchRoute:
    city: str
    query: str
    url: str


def build_search_routes(cities: list[str], queries: list[str]) -> tuple[SearchRoute, ...]:
    """Build deterministic official BOSS search URLs for supported cities."""

    routes: list[SearchRoute] = []
    for city in cities:
        code = CITY_CODES.get(city)
        if code is None:
            raise ValueError(f"unsupported BOSS city: {city}")
        for query in queries:
            normalized_query = query.strip()
            if not normalized_query:
                continue
            params = urlencode({"city": code, "query": normalized_query})
            routes.append(SearchRoute(city, normalized_query, f"{SEARCH_URL}?{params}"))
    if not routes:
        raise ValueError("at least one city and query are required")
    return tuple(routes)


class BossTargetedJobSource:
    """Capture a small number of jobs from each route in one browser session."""

    def __init__(self, routes: tuple[SearchRoute, ...], *, per_route_limit: int = 5) -> None:
        if not routes:
            raise ValueError("targeted capture requires search routes")
        if per_route_limit < 1:
            raise ValueError("per-route limit must be at least 1")
        self.routes = routes
        self.per_route_limit = per_route_limit

    async def capture_jobs(self, limit: int) -> tuple[JobSnapshot, ...]:
        if limit < 1:
            raise ValueError("capture limit must be at least 1")
        first = self.routes[0]
        await finding_jobs.open_browser_with_options(first.url, "chrome")
        await finding_jobs.log_in()
        await finding_jobs.navigate_to_url(first.url)

        captured: list[JobSnapshot] = []
        seen_keys: set[str] = set()
        for index, route in enumerate(self.routes):
            if len(captured) >= limit:
                break
            try:
                if index:
                    await finding_jobs.navigate_to_url(route.url)
                if not await finding_jobs.wait_for_real_job_cards(timeout=30):
                    log.warning("搜索页无岗位卡，跳过 %s / %s", route.city, route.query)
                    continue
                route_limit = min(self.per_route_limit, limit - len(captured))
                snapshots = await _capture_current_feed(route_limit)
            except (TimeoutError, RuntimeError) as exc:
                log.warning("搜索页读取失败，跳过 %s / %s：%s", route.city, route.query, exc)
                continue
            for snapshot in snapshots:
                key = canonical_job_key(snapshot)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                captured.append(snapshot)
            log.info(
                "目标搜索完成：%s / %s，累计 %d 个唯一岗位",
                route.city,
                route.query,
                len(captured),
            )
        return tuple(captured)
