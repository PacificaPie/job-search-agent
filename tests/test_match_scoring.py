"""Versioned production match-scoring contract tests."""

from boss_zhipin.domain.campaign import (
    CHINA_CAMPUS_CAMPAIGN,
    GLOBAL_NEW_GRAD_CAMPAIGN,
)
from boss_zhipin.models.match_scoring import (
    GLOBAL_MATCH_POLICY,
    build_match_scoring_prompt,
    match_scoring_policy,
    parse_match_scoring_response,
)


def test_prompt_builder_selects_campaign_specific_hard_rules():
    china = build_match_scoring_prompt(
        job_description="2027 校招 AI 产品经理",
        resume_text="AI 产品经历",
        matched_keywords=["AI"],
        campaign_key=CHINA_CAMPUS_CAMPAIGN.campaign_key,
    )
    global_prompt = build_match_scoring_prompt(
        job_description="AI PM New Grad",
        resume_text="AI product experience",
        campaign_key=GLOBAL_NEW_GRAD_CAMPAIGN.campaign_key,
    )

    assert "外包/劳务派遣" in china
    assert "2027 校招 AI 产品经理" in china
    assert "Sponsorship" in global_prompt
    assert match_scoring_policy(GLOBAL_NEW_GRAD_CAMPAIGN.campaign_key) is GLOBAL_MATCH_POLICY


def test_response_parser_is_strict_inside_and_tolerant_only_at_outer_fence():
    parsed = parse_match_scoring_response(
        '```json\n{"score": 88.4, "keywords": ["RAG"], "reason": "职责匹配"}\n```'
    )
    assert parsed == {"score": 88, "keywords": ["RAG"], "reason": "职责匹配"}

    try:
        parse_match_scoring_response('{"score": "high", "keywords": []}')
    except ValueError as exc:
        assert "numeric score" in str(exc)
    else:
        raise AssertionError("non-numeric scores must not enter production evaluations")
