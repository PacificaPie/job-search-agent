"""Application status machine shared by persistence and application services.

投递状态机是这套系统里唯一能算出真实回调率的地方（蓝图第 4 节），所以状态流转
必须是显式白名单而不是"随便写个字符串进去"：一旦有人把 ``submitted`` 直接改成
``offer``，中间那段转化率就永远补不回来了。

面试轮次用 ``interview_1`` / ``interview_2`` … 表示（蓝图写的 ``interview_1..n``），
所以合法状态不是一个有限枚举，得配一个校验函数。
"""

from __future__ import annotations

import re
from enum import StrEnum


class ApplicationStatus(StrEnum):
    """固定状态。面试轮次不在这里，见 ``interview_status``。"""

    PREPARING = "preparing"
    READY = "ready"
    SUBMITTED = "submitted"
    SCREENING = "screening"
    OFFER = "offer"
    REJECTED = "rejected"
    GHOSTED = "ghosted"
    WITHDRAWN = "withdrawn"


class ApplicationChannel(StrEnum):
    """投递渠道（蓝图第 4 节）。"""

    BOSS_CHAT = "boss_chat"
    LINKEDIN_EASY = "linkedin_easy"
    COMPANY_SITE = "company_site"
    REFERRAL = "referral"


#: 终态。``ghosted`` 不在这里——公司晚回是常事，允许被"唤醒"。
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
)

_INTERVIEW_RE = re.compile(r"^interview_([1-9]\d?)$")
_MAX_INTERVIEW_ROUND = 99


def interview_status(round_number: int) -> str:
    """``interview_status(2) == "interview_2"``。"""

    if not 1 <= round_number <= _MAX_INTERVIEW_ROUND:
        raise ValueError(f"interview round out of range: {round_number}")
    return f"interview_{round_number}"


def interview_round(status: str) -> int | None:
    """面试轮次，非面试状态返回 None。"""

    match = _INTERVIEW_RE.match(status)
    return int(match.group(1)) if match else None


def is_valid_status(status: str) -> bool:
    return status in set(ApplicationStatus) or interview_round(status) is not None


def _after_interview(round_number: int) -> frozenset[str]:
    allowed = {
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.GHOSTED.value,
        ApplicationStatus.WITHDRAWN.value,
    }
    if round_number < _MAX_INTERVIEW_ROUND:
        allowed.add(interview_status(round_number + 1))
    return frozenset(allowed)


_TRANSITIONS: dict[str, frozenset[str]] = {
    # 还没投出去：可以回退，也可以直接放弃
    ApplicationStatus.PREPARING.value: frozenset(
        {ApplicationStatus.READY.value, ApplicationStatus.WITHDRAWN.value}
    ),
    ApplicationStatus.READY.value: frozenset(
        {
            ApplicationStatus.PREPARING.value,
            ApplicationStatus.SUBMITTED.value,
            ApplicationStatus.WITHDRAWN.value,
        }
    ),
    # 投出去之后就不允许回退了——回调率的分母必须稳定
    ApplicationStatus.SUBMITTED.value: frozenset(
        {
            ApplicationStatus.SCREENING.value,
            interview_status(1),
            ApplicationStatus.REJECTED.value,
            ApplicationStatus.GHOSTED.value,
            ApplicationStatus.WITHDRAWN.value,
        }
    ),
    ApplicationStatus.SCREENING.value: frozenset(
        {
            interview_status(1),
            ApplicationStatus.REJECTED.value,
            ApplicationStatus.GHOSTED.value,
            ApplicationStatus.WITHDRAWN.value,
        }
    ),
    # 已读不回之后又收到回复：允许回到流程里，但不能倒回 submitted
    ApplicationStatus.GHOSTED.value: frozenset(
        {
            ApplicationStatus.SCREENING.value,
            interview_status(1),
            ApplicationStatus.REJECTED.value,
            ApplicationStatus.WITHDRAWN.value,
        }
    ),
    ApplicationStatus.OFFER.value: frozenset({ApplicationStatus.WITHDRAWN.value}),
    ApplicationStatus.REJECTED.value: frozenset(),
    ApplicationStatus.WITHDRAWN.value: frozenset(),
}


def allowed_transitions(status: str) -> frozenset[str]:
    """当前状态允许流转到哪些状态。未知状态抛 ValueError。"""

    round_number = interview_round(status)
    if round_number is not None:
        return _after_interview(round_number)
    if status not in _TRANSITIONS:
        raise ValueError(f"unknown application status: {status}")
    return _TRANSITIONS[status]


def ensure_transition(current: str, target: str) -> None:
    """校验一次流转，非法就抛 ValueError（带上合法选项，方便 UI 直接显示）。"""

    if not is_valid_status(target):
        raise ValueError(f"unknown application status: {target}")
    if current == target:
        raise ValueError(f"application is already in status: {target}")
    allowed = allowed_transitions(current)
    if target not in allowed:
        options = "、".join(sorted(allowed)) or "（终态，不可再流转）"
        raise ValueError(f"不允许的状态流转：{current} → {target}；当前可选：{options}")
