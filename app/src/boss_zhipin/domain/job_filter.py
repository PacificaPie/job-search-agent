"""Deterministic pre-filtering before any LLM evaluation or human review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuleState(StrEnum):
    ELIGIBLE = "eligible"
    FILTERED = "filtered"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True, slots=True)
class JobFilterConfig:
    target_cities: tuple[str, ...] = ()
    target_roles: tuple[str, ...] = ()
    employment_types: tuple[str, ...] = ()
    title_excludes: tuple[str, ...] = ()
    content_excludes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuleMatch:
    state: RuleState
    reasons: tuple[str, ...]
    matched_city: str | None = None
    matched_role: str | None = None
    matched_employment_type: str | None = None


_CAMPUS_SIGNALS = ("2027", "27届", "校招", "校园招聘", "应届", "毕业生")
_UNKNOWN_CITY_REASON = "岗位未提供城市信息（location 为空且正文无城市线索），需人工确认"


def evaluate_job_rules(
    *,
    title: str,
    location: str,
    description: str,
    config: JobFilterConfig,
) -> RuleMatch:
    """Classify one job with explainable, conservative local rules."""

    title_text = title.casefold()
    location_text = location.casefold()
    combined = f"{title}\n{location}\n{description}".casefold()

    for keyword in config.title_excludes:
        if keyword.casefold() in title_text:
            return RuleMatch(RuleState.FILTERED, (f"岗位名称命中排除词：{keyword}",))
    for keyword in config.content_excludes:
        if keyword.casefold() in combined:
            return RuleMatch(RuleState.FILTERED, (f"岗位信息命中排除词：{keyword}",))

    matched_city = next(
        (city for city in config.target_cities if city.casefold() in location_text),
        None,
    )
    # capture 层经常拿不到 location（BOSS 把地址放在详情正文的「工作地址」里），
    # 此时不能当成"不在目标城市"硬杀：先回退正文找城市，仍找不到就留到最后降级人工。
    city_from_description = False
    city_unknown = False
    if config.target_cities and matched_city is None:
        if location_text.strip():
            return RuleMatch(RuleState.FILTERED, ("不在目标城市范围",))
        description_text = description.casefold()
        matched_city = next(
            (city for city in config.target_cities if city.casefold() in description_text),
            None,
        )
        city_from_description = matched_city is not None
        city_unknown = matched_city is None

    matched_role = next(
        (role for role in config.target_roles if role.casefold() in title_text),
        None,
    )
    if config.target_roles and matched_role is None:
        return RuleMatch(RuleState.FILTERED, ("岗位名称不属于目标产品方向",), matched_city)

    matched_employment_type = None
    if config.employment_types:
        campus_only = any(value in {"2027校招", "校招"} for value in config.employment_types)
        accepts_internships = any("实习" in value for value in config.employment_types)
        if campus_only and not accepts_internships and "实习" in title_text:
            return RuleMatch(
                RuleState.FILTERED,
                ("仅筛选校招正式岗，岗位名称为实习岗",),
                matched_city,
                matched_role,
            )
        if campus_only:
            matched_employment_type = next(
                (signal for signal in _CAMPUS_SIGNALS if signal.casefold() in combined),
                None,
            )
        else:
            matched_employment_type = next(
                (value for value in config.employment_types if value.casefold() in combined),
                None,
            )
        if matched_employment_type is None:
            reasons = ("未找到明确的 2027 校招/应届标识",)
            if city_unknown:
                reasons += (_UNKNOWN_CITY_REASON,)
            return RuleMatch(
                RuleState.NEEDS_REVIEW,
                reasons,
                matched_city,
                matched_role,
            )

    if city_unknown:
        return RuleMatch(
            RuleState.NEEDS_REVIEW,
            (_UNKNOWN_CITY_REASON,),
            None,
            matched_role,
            matched_employment_type,
        )

    city_reason = ""
    if matched_city:
        city_reason = f"城市（正文推断）：{matched_city}" if city_from_description else f"城市：{matched_city}"
    reasons = tuple(
        reason
        for reason in (
            city_reason,
            f"岗位：{matched_role}" if matched_role else "",
            f"招聘类型：{matched_employment_type}" if matched_employment_type else "",
        )
        if reason
    )
    return RuleMatch(
        RuleState.ELIGIBLE,
        reasons or ("未配置预筛规则",),
        matched_city,
        matched_role,
        matched_employment_type,
    )
