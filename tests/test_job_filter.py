"""Deterministic local targeting-rule tests."""

from boss_zhipin.domain.job_filter import JobFilterConfig, RuleState, evaluate_job_rules


CONFIG = JobFilterConfig(
    target_cities=("北京", "上海", "深圳", "广州"),
    target_roles=("AI产品经理", "策略产品经理", "产品经理"),
    employment_types=("2027校招",),
    title_excludes=("销售", "运营", "实施"),
    content_excludes=("外包", "驻场"),
)


def test_matching_campus_product_role_is_eligible():
    result = evaluate_job_rules(
        title="AI产品经理-2027校招",
        location="北京·海淀区",
        description="负责大模型应用产品设计，面向2027届毕业生。",
        config=CONFIG,
    )
    assert result.state is RuleState.ELIGIBLE
    assert result.matched_city == "北京"
    assert result.matched_role == "AI产品经理"


def test_title_and_content_exclusions_are_strict():
    title_result = evaluate_job_rules(
        title="产品运营-2027校招",
        location="上海",
        description="负责产品增长",
        config=CONFIG,
    )
    content_result = evaluate_job_rules(
        title="策略产品经理-2027校招",
        location="深圳",
        description="该岗位需要长期驻场",
        config=CONFIG,
    )
    assert title_result.state is RuleState.FILTERED
    assert "运营" in title_result.reasons[0]
    assert content_result.state is RuleState.FILTERED
    assert "驻场" in content_result.reasons[0]


def test_missing_campus_signal_requires_human_review():
    result = evaluate_job_rules(
        title="策略产品经理",
        location="广州",
        description="负责平台机制和策略设计",
        config=CONFIG,
    )
    assert result.state is RuleState.NEEDS_REVIEW
    assert result.matched_role == "策略产品经理"


def test_internship_is_filtered_when_only_campus_roles_are_requested():
    result = evaluate_job_rules(
        title="AI产品经理实习生",
        location="广州",
        description="表现优秀可获得2027校招 HC",
        config=CONFIG,
    )
    assert result.state is RuleState.FILTERED
    assert "实习岗" in result.reasons[0]


def test_wrong_city_or_role_is_filtered():
    wrong_city = evaluate_job_rules(
        title="AI产品经理-2027校招",
        location="杭州",
        description="校园招聘",
        config=CONFIG,
    )
    wrong_role = evaluate_job_rules(
        title="算法工程师-2027校招",
        location="北京",
        description="校园招聘",
        config=CONFIG,
    )
    assert wrong_city.state is RuleState.FILTERED
    assert wrong_role.state is RuleState.FILTERED
