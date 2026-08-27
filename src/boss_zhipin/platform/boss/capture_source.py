"""Read-only BOSS feed adapter for the capture-only workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from boss_zhipin.domain.job_identity import canonical_job_key
from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.website_oper import finding_jobs

log = logging.getLogger(__name__)

DEFAULT_RECOMMEND_URL = (
    "https://www.zhipin.com/web/geek/job-recommend?ka=header-job-recommend"
)


@dataclass(frozen=True, slots=True)
class BossCaptureConfig:
    label: str = ""
    url: str = DEFAULT_RECOMMEND_URL
    browser_type: str = "chrome"
    max_no_progress: int = 5


class BossJobSource:
    """Capture visible jobs through nodriver without opening a conversation."""

    def __init__(self, config: BossCaptureConfig | None = None) -> None:
        self.config = config or BossCaptureConfig()

    async def capture_jobs(self, limit: int) -> tuple[JobSnapshot, ...]:
        if limit < 1:
            raise ValueError("capture limit must be at least 1")
        await finding_jobs.open_browser_with_options(
            self.config.url, self.config.browser_type
        )
        await finding_jobs.log_in()
        await finding_jobs.select_dropdown_option(self.config.label)
        if not await finding_jobs.wait_for_real_job_cards(timeout=30):
            raise RuntimeError("岗位列表未渲染，capture-only 无法开始")

        captured = await _capture_current_feed(
            limit, max_no_progress=self.config.max_no_progress
        )
        log.info("capture-only 完成：读取 %d 个唯一岗位", len(captured))
        return captured


async def _capture_current_feed(
    limit: int, *, max_no_progress: int = 5
) -> tuple[JobSnapshot, ...]:
    captured: list[JobSnapshot] = []
    seen_keys: set[str] = set()
    visible_index = 1
    no_progress = 0

    while len(captured) < limit and no_progress < max_no_progress:
        loaded_count = await finding_jobs.get_loaded_job_count()
        if loaded_count < 1:
            no_progress += 1
            if not await finding_jobs.scroll_to_load_more_jobs():
                break
            continue

        if visible_index > loaded_count:
            before_count = loaded_count
            if not await finding_jobs.scroll_to_load_more_jobs():
                break
            loaded_count = await finding_jobs.get_loaded_job_count()
            if loaded_count <= before_count:
                visible_index = max(1, loaded_count)
            continue

        snapshot = await finding_jobs.get_job_snapshot_by_index(visible_index)
        visible_index += 1
        if snapshot is None:
            no_progress += 1
            continue
        key = canonical_job_key(snapshot)
        if key in seen_keys:
            no_progress += 1
            continue
        seen_keys.add(key)
        captured.append(snapshot)
        no_progress = 0

    return tuple(captured)
