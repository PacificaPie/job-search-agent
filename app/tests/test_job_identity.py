"""Versioned job identity and normalization tests."""

from boss_zhipin.domain.job_identity import canonical_job_key, normalize_job_url, normalize_text
from boss_zhipin.domain.models import JobSnapshot


def test_external_id_is_strongest_identity():
    first = JobSnapshot(title="Backend", company="A", external_id="job-123")
    changed = JobSnapshot(title="Senior Backend", company="B", external_id="job-123")
    assert canonical_job_key(first) == canonical_job_key(changed)


def test_same_external_id_on_different_platforms_does_not_collide():
    boss = JobSnapshot(title="AI PM", platform="boss_zhipin", external_id="123")
    linkedin = JobSnapshot(title="AI PM", platform="linkedin", external_id="123")
    assert canonical_job_key(boss) != canonical_job_key(linkedin)


def test_url_identity_ignores_tracking_and_fragment():
    first = JobSnapshot(
        title="Backend",
        source_url="https://www.zhipin.com/job_detail/abc.html?lid=one&foo=bar#top",
    )
    second = JobSnapshot(
        title="Changed title",
        source_url="https://www.zhipin.com/job_detail/abc.html?foo=bar&securityId=two",
    )
    assert canonical_job_key(first) == canonical_job_key(second)


def test_content_fallback_normalizes_whitespace_and_case():
    first = JobSnapshot(
        title="AI  Product Manager",
        company="Example Inc",
        location="Shanghai",
        description="Build   useful agents",
    )
    second = JobSnapshot(
        title=" ai product manager ",
        company="EXAMPLE INC",
        location="shanghai",
        description="Build useful agents",
    )
    assert canonical_job_key(first) == canonical_job_key(second)


def test_meaningful_content_change_changes_fallback_identity():
    first = JobSnapshot(title="Backend", company="A", description="Python")
    second = JobSnapshot(title="Backend", company="A", description="Java")
    assert canonical_job_key(first) != canonical_job_key(second)


def test_normalizers_are_deterministic():
    assert normalize_text("  Hello\n WORLD ") == "hello world"
    assert normalize_job_url("not-a-url") == "not-a-url"


def test_empty_snapshot_is_rejected():
    try:
        JobSnapshot(title="", description="  ")
    except ValueError as exc:
        assert "title or description" in str(exc)
    else:
        raise AssertionError("empty snapshot should fail")


def test_empty_platform_is_rejected():
    try:
        JobSnapshot(title="AI PM", platform=" ")
    except ValueError as exc:
        assert "platform" in str(exc)
    else:
        raise AssertionError("empty platform should fail")
