"""Versioned, Campaign-specific match-scoring prompts and response parsing.

This module is the production source of truth. The independent ``evals`` repo
imports these builders directly so an eval can never pass against a prompt that
the app does not actually use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from boss_zhipin.domain.campaign import (
    CHINA_CAMPUS_CAMPAIGN,
    GLOBAL_NEW_GRAD_CAMPAIGN,
)


@dataclass(frozen=True, slots=True)
class MatchScoringPolicy:
    campaign_key: str
    prompt_version: str
    template: str


_OUTPUT_INSTRUCTIONS = """## 输出（严格 JSON，机器直接解析）
只输出一个 JSON 对象，不要 markdown 代码块围栏，不要任何前后说明文字。

{"score": <0-100>, "keywords": [...], "reason": "<150字内，给出对应关系与主要差距>"}

字符串值里不允许出现半角双引号；引用原文时改用中文引号。"""

_CHINA_TEMPLATE = """你是求职匹配评估器。根据候选人背景与岗位 JD，输出 0-100 匹配分。

## 硬规则（优先于语义匹配）
1. 招聘主体是外包/劳务派遣/人力服务公司（即使标题挂品牌方名）→ 分数 ≤ 40，并在理由中指出。
2. 岗位有明确的行业/年限硬门槛且候选人不满足 → 分数 ≤ 45。
3. 校招属性明确（2027/应届/校招）是加分锚点，需在理由中确认。

## 语义匹配
- 逐项对照 JD 核心职责与候选人经历，理由中给出对应关系。
- 候选人独特背景与岗位领域重合（如生物统计×医疗）应识别为加成。
- 不得假设候选人拥有材料中未出现的经历。

{output_instructions}

---
岗位 JD：
{jd}

候选人背景：
{resume}

已命中的简历关键词：
{matched_keywords}
"""

_GLOBAL_TEMPLATE = """你是海外 New Grad 求职匹配评估器。根据候选人背景与岗位 JD，输出 0-100 匹配分。

## 硬规则（优先于语义匹配）
1. 岗位明确要求 3 年及以上相关经验、或标题为 Senior/Staff/Principal/Director，而候选人不满足 → 分数 ≤ 45。
2. 候选人需要工作签证支持；岗位明确不提供 Sponsorship → 分数 ≤ 30，并在理由中指出。
3. 岗位未说明 Sponsorship → 分数 ≤ 65，理由中明确标记 Sponsorship 待核对，不得自行假设支持。
4. 明确的 2027/New Grad/Early Career 属性是加分锚点；明显的社招岗位不得因 AI/PM 关键词给高分。

## 语义匹配
- 对照 AI/ML 产品、数据分析、实验评估、跨团队推进等核心职责与候选人事实。
- 医疗、生物统计、风控等领域重合可以加分，但不能覆盖年限和签证硬门槛。
- 不得假设候选人拥有材料中未出现的经历或工作授权。

{output_instructions}

---
Job Description：
{jd}

Candidate Background：
{resume}

Matched Resume Keywords：
{matched_keywords}
"""

CHINA_MATCH_POLICY = MatchScoringPolicy(
    campaign_key=CHINA_CAMPUS_CAMPAIGN.campaign_key,
    prompt_version="cn-match-v2",
    template=_CHINA_TEMPLATE,
)
GLOBAL_MATCH_POLICY = MatchScoringPolicy(
    campaign_key=GLOBAL_NEW_GRAD_CAMPAIGN.campaign_key,
    prompt_version="global-match-v1",
    template=_GLOBAL_TEMPLATE,
)
MATCH_SCORING_POLICIES = {
    policy.campaign_key: policy for policy in (CHINA_MATCH_POLICY, GLOBAL_MATCH_POLICY)
}


def match_scoring_policy(campaign_key: str) -> MatchScoringPolicy:
    try:
        return MATCH_SCORING_POLICIES[campaign_key]
    except KeyError as exc:
        raise ValueError(f"unsupported match-scoring campaign: {campaign_key}") from exc


def build_match_scoring_prompt(
    *,
    job_description: str,
    resume_text: str,
    matched_keywords: list[str] | tuple[str, ...] = (),
    campaign_key: str = CHINA_CAMPUS_CAMPAIGN.campaign_key,
) -> str:
    policy = match_scoring_policy(campaign_key)
    return policy.template.format(
        output_instructions=_OUTPUT_INSTRUCTIONS,
        jd=job_description.strip(),
        resume=resume_text.strip(),
        matched_keywords="、".join(matched_keywords) or "无（按完整材料评估）",
    )


def parse_match_scoring_response(content: str) -> dict[str, object]:
    """Parse the strict JSON contract while tolerating an outer Markdown fence."""

    normalized = content.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```")
        normalized = normalized.removesuffix("```").strip()
    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("match-scoring response must be a JSON object")
    raw_score = payload.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise ValueError("match-scoring response requires a numeric score")
    score = min(100, max(0, int(round(raw_score))))
    reason = str(payload.get("reason") or "").strip()
    raw_keywords = payload.get("keywords") or []
    if not isinstance(raw_keywords, list) or not all(
        isinstance(keyword, str) for keyword in raw_keywords
    ):
        raise ValueError("match-scoring keywords must be a string list")
    return {"score": score, "reason": reason, "keywords": raw_keywords}
