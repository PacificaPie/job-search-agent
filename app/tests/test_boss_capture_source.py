"""Read-only BOSS source orchestration tests."""

from __future__ import annotations

import asyncio

from boss_zhipin.domain.models import JobSnapshot
from boss_zhipin.platform.boss.capture_source import BossCaptureConfig, BossJobSource
from boss_zhipin.website_oper import finding_jobs


def test_source_reads_jobs_without_contact_actions(monkeypatch):
    calls: list[tuple] = []

    async def open_browser(url: str, browser_type: str):
        calls.append(("open", url, browser_type))

    async def login():
        calls.append(("login",))

    async def select(label: str):
        calls.append(("select", label))

    async def wait_cards(timeout: float):
        calls.append(("wait", timeout))
        return True

    async def count():
        return 2

    async def snapshot(index: int):
        return JobSnapshot(
            title=f"Job {index}", external_id=f"id-{index}", description="JD"
        )

    async def unexpected_scroll(*args, **kwargs):
        raise AssertionError("scroll should not be needed for two visible jobs")

    monkeypatch.setattr(finding_jobs, "open_browser_with_options", open_browser)
    monkeypatch.setattr(finding_jobs, "log_in", login)
    monkeypatch.setattr(finding_jobs, "select_dropdown_option", select)
    monkeypatch.setattr(finding_jobs, "wait_for_real_job_cards", wait_cards)
    monkeypatch.setattr(finding_jobs, "get_loaded_job_count", count)
    monkeypatch.setattr(finding_jobs, "get_job_snapshot_by_index", snapshot)
    monkeypatch.setattr(finding_jobs, "scroll_to_load_more_jobs", unexpected_scroll)

    source = BossJobSource(BossCaptureConfig(label="AI 产品", url="https://example.test"))
    jobs = asyncio.run(source.capture_jobs(2))
    assert [job.external_id for job in jobs] == ["id-1", "id-2"]
    assert calls == [
        ("open", "https://example.test", "chrome"),
        ("login",),
        ("select", "AI 产品"),
        ("wait", 30),
    ]


def test_source_stops_when_feed_cannot_progress(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    async def ready(*args, **kwargs):
        return True

    async def count():
        return 1

    async def snapshot(index: int):
        return JobSnapshot(title="Same job", external_id="same", description="JD")

    async def cannot_scroll(*args, **kwargs):
        return False

    monkeypatch.setattr(finding_jobs, "open_browser_with_options", noop)
    monkeypatch.setattr(finding_jobs, "log_in", noop)
    monkeypatch.setattr(finding_jobs, "select_dropdown_option", noop)
    monkeypatch.setattr(finding_jobs, "wait_for_real_job_cards", ready)
    monkeypatch.setattr(finding_jobs, "get_loaded_job_count", count)
    monkeypatch.setattr(finding_jobs, "get_job_snapshot_by_index", snapshot)
    monkeypatch.setattr(finding_jobs, "scroll_to_load_more_jobs", cannot_scroll)

    jobs = asyncio.run(BossJobSource().capture_jobs(10))
    assert len(jobs) == 1
