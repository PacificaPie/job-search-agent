"""Deterministic rules for the personal US LinkedIn new-grad search."""

from __future__ import annotations

import re
from dataclasses import dataclass

from boss_zhipin.domain.job_filter import RuleMatch, RuleState


@dataclass(frozen=True, slots=True)
class LinkedInFilterConfig:
    locations: tuple[str, ...]
    role_signals: tuple[str, ...]
    graduation_year: str = "2027"
    sponsorship_required: bool = True


DEFAULT_LINKEDIN_FILTER = LinkedInFilterConfig(
    locations=("New York", "San Francisco", "Boston", "Washington", "Austin"),
    role_signals=(
        "AI Product Manager",
        "AI/ML Product Manager",
        "Machine Learning Product Manager",
        "Generative AI Product Manager",
        "GenAI Product Manager",
        "Product Strategy",
    ),
)

_SENIOR_TITLE_SIGNALS = ("senior", "sr.", "staff", "principal", "director", "head of", "vice president", "vp ")
_SPONSORSHIP_NEGATIVE = (
    "will not sponsor",
    "does not sponsor",
    "do not sponsor",
    "cannot sponsor",
    "can't sponsor",
    "unable to sponsor",
    "no sponsorship",
    "without sponsorship",
    "not eligible for sponsorship",
    "us persons only",
    "u.s. persons only",
)
_SPONSORSHIP_POSITIVE = (
    "sponsorship is available",
    "sponsorship available",
    "visa sponsorship available",
    "will sponsor",
    "we sponsor",
    "offers sponsorship",
    "offer sponsorship",
    "h-1b sponsorship",
    "h1b sponsorship",
    "immigration sponsorship",
)
_NEW_GRAD_SIGNALS = (
    "new grad",
    "new graduate",
    "recent graduate",
    "university graduate",
    "early career",
    "entry level",
    "entry-level",
    "campus",
)
_AI_CONTEXT_SIGNALS = (
    "artificial intelligence",
    "machine learning",
    "generative ai",
    "genai",
    "large language model",
    "llm",
    "foundation model",
    "core models",
    "ai-enabled",
    "ai product",
    "openai",
)
_EXPERIENCED_RE = re.compile(r"\b(?:[3-9]|[1-9]\d)\s*\+?\s*years?\b", re.IGNORECASE)


def evaluate_linkedin_job_rules(
    *,
    title: str,
    location: str,
    description: str,
    config: LinkedInFilterConfig = DEFAULT_LINKEDIN_FILTER,
) -> RuleMatch:
    """Classify a LinkedIn job for city, level, graduation year and sponsorship."""
    title_text = title.casefold()
    location_text = location.casefold()
    combined = f"{title}\n{location}\n{description}".casefold()

    matched_city = next(
        (city for city in config.locations if city.casefold() in location_text),
        None,
    )
    if matched_city is None:
        return RuleMatch(RuleState.FILTERED, ("不在目标美国城市范围",))

    matched_role = next(
        (role for role in config.role_signals if role.casefold() in title_text),
        None,
    )
    if matched_role is None and "product manager" in title_text:
        ai_context = next((signal for signal in _AI_CONTEXT_SIGNALS if signal in combined), None)
        if ai_context:
            matched_role = f"AI Product Manager（语义：{ai_context}）"
    if matched_role is None:
        return RuleMatch(RuleState.FILTERED, ("岗位名称不属于目标 AI/策略产品方向",), matched_city)

    senior_signal = next((value for value in _SENIOR_TITLE_SIGNALS if value in title_text), None)
    if senior_signal or _EXPERIENCED_RE.search(description):
        reason = f"岗位名称命中资深级别：{senior_signal}" if senior_signal else "岗位要求至少 3 年经验"
        return RuleMatch(RuleState.FILTERED, (reason,), matched_city, matched_role)

    sponsorship_negative = next(
        (value for value in _SPONSORSHIP_NEGATIVE if value in combined),
        None,
    )
    if sponsorship_negative:
        return RuleMatch(
            RuleState.FILTERED,
            (f"明确不支持 Sponsorship：{sponsorship_negative}",),
            matched_city,
            matched_role,
        )

    has_year = config.graduation_year.casefold() in combined
    new_grad_signal = next((value for value in _NEW_GRAD_SIGNALS if value in combined), None)
    if not has_year:
        return RuleMatch(
            RuleState.NEEDS_REVIEW,
            (f"未找到明确的 {config.graduation_year} 招聘标识",),
            matched_city,
            matched_role,
            new_grad_signal,
        )

    sponsorship_positive = next(
        (value for value in _SPONSORSHIP_POSITIVE if value in combined),
        None,
    )
    if config.sponsorship_required and sponsorship_positive is None:
        return RuleMatch(
            RuleState.NEEDS_REVIEW,
            ("未找到明确的 Sponsorship 支持承诺",),
            matched_city,
            matched_role,
            config.graduation_year,
        )

    return RuleMatch(
        RuleState.ELIGIBLE,
        (
            f"城市：{matched_city}",
            f"岗位：{matched_role}",
            f"毕业年份：{config.graduation_year}",
            f"签证：{sponsorship_positive}",
        ),
        matched_city,
        matched_role,
        config.graduation_year,
    )
