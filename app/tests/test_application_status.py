"""投递状态机规则测试。"""

import pytest

from boss_zhipin.domain.application_status import (
    ApplicationStatus,
    allowed_transitions,
    ensure_transition,
    interview_round,
    interview_status,
    is_valid_status,
)


def test_interview_rounds_round_trip():
    assert interview_status(1) == "interview_1"
    assert interview_round("interview_12") == 12
    assert interview_round("submitted") is None
    assert is_valid_status("interview_3")
    assert is_valid_status(ApplicationStatus.OFFER.value)
    assert not is_valid_status("interview_0")
    assert not is_valid_status("hired")


def test_happy_path_walks_the_whole_funnel():
    path = [
        "preparing",
        "ready",
        "submitted",
        "screening",
        "interview_1",
        "interview_2",
        "offer",
    ]
    for current, target in zip(path, path[1:]):
        ensure_transition(current, target)


def test_submitted_cannot_be_rolled_back_or_skipped():
    """回调率的分母必须稳定：投出去之后不能倒回，也不能跳过面试直接 offer。"""
    with pytest.raises(ValueError):
        ensure_transition("submitted", "ready")
    with pytest.raises(ValueError):
        ensure_transition("submitted", "offer")


def test_ghosted_can_be_revived_but_rejected_is_terminal():
    ensure_transition("ghosted", "interview_1")
    assert allowed_transitions("rejected") == frozenset()
    with pytest.raises(ValueError):
        ensure_transition("rejected", "screening")


def test_no_op_and_unknown_status_are_rejected():
    with pytest.raises(ValueError, match="already in status"):
        ensure_transition("submitted", "submitted")
    with pytest.raises(ValueError, match="unknown application status"):
        ensure_transition("submitted", "hired")
    with pytest.raises(ValueError, match="unknown application status"):
        allowed_transitions("hired")


def test_error_message_lists_the_legal_options():
    with pytest.raises(ValueError) as excinfo:
        ensure_transition("preparing", "submitted")
    assert "ready" in str(excinfo.value)
