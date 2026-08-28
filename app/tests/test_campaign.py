"""Built-in campaign routing contract tests."""

from boss_zhipin.domain.campaign import (
    ActionStrategy,
    CHINA_CAMPUS_CAMPAIGN,
    GLOBAL_NEW_GRAD_CAMPAIGN,
    campaign_spec_for_platform,
)


def test_platforms_route_to_campaign_specific_action_strategies():
    boss = campaign_spec_for_platform("boss_zhipin")
    linkedin = campaign_spec_for_platform(" LinkedIn ")
    company_site = campaign_spec_for_platform("company_site")

    assert boss is CHINA_CAMPUS_CAMPAIGN
    assert boss.action_strategy is ActionStrategy.BOSS_FIXED_GREETING
    assert boss.requires_generated_materials is False
    assert linkedin is GLOBAL_NEW_GRAD_CAMPAIGN
    assert company_site is GLOBAL_NEW_GRAD_CAMPAIGN
    assert linkedin.requires_generated_materials is True


def test_unknown_platform_does_not_silently_join_a_campaign():
    try:
        campaign_spec_for_platform("unknown_board")
    except ValueError as exc:
        assert "unsupported campaign source platform" in str(exc)
    else:
        raise AssertionError("unknown platforms must remain explicitly unassigned")
