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


def test_blank_location_falls_back_to_description_city():
    """capture 层留空 location 时，正文里的「工作地址 北京…」应当被认出来。"""
    result = evaluate_job_rules(
        title="AI产品经理",
        location="",
        description="工作地址 北京大兴区京东总部2号楼A座。面向2027届校招。",
        config=CONFIG,
    )
    assert result.state is RuleState.ELIGIBLE
    assert result.matched_city == "北京"
    assert any("正文推断" in reason for reason in result.reasons)


def test_blank_location_without_city_clue_needs_review_not_filtered():
    """城市完全未知时降级人工，不能当成「不在目标城市」硬杀。"""
    result = evaluate_job_rules(
        title="AI产品经理",
        location="",
        description="负责大模型产品设计，面向2027届毕业生。",
        config=CONFIG,
    )
    assert result.state is RuleState.NEEDS_REVIEW
    assert any("未提供城市信息" in reason for reason in result.reasons)


def test_unknown_city_still_loses_to_role_and_exclusion_rules():
    """城市未知不应该把无关岗位灌进人工队列——排除词和岗位方向仍然先杀。"""
    wrong_role = evaluate_job_rules(
        title="数据科学家",
        location="",
        description="2027校招，负责用户画像。",
        config=CONFIG,
    )
    excluded = evaluate_job_rules(
        title="AI产品经理",
        location="",
        description="该岗位需要长期驻场，2027校招。",
        config=CONFIG,
    )
    assert wrong_role.state is RuleState.FILTERED
    assert excluded.state is RuleState.FILTERED


def test_non_empty_wrong_city_is_still_filtered_without_description_fallback():
    """location 有值但不在目标城市 → 保持硬杀，正文里的城市词不该救它。"""
    result = evaluate_job_rules(
        title="AI产品经理",
        location="乌鲁木齐·新市区",
        description="总部位于北京，本岗位2027校招。",
        config=CONFIG,
    )
    assert result.state is RuleState.FILTERED
    assert result.reasons[0] == "不在目标城市范围"
