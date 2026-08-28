"""Domain vocabulary for independent job-search campaigns."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActionStrategy(StrEnum):
    """The human-gated outcome prepared after a job is selected."""

    BOSS_FIXED_GREETING = "boss_fixed_greeting"
    TAILORED_APPLICATION = "tailored_application"


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    """Stable routing contract shared by the app and offline evals."""

    campaign_key: str
    name: str
    source_platforms: tuple[str, ...]
    action_strategy: ActionStrategy
    evaluation_policy_version: str

    @property
    def requires_generated_materials(self) -> bool:
        return self.action_strategy is ActionStrategy.TAILORED_APPLICATION


CHINA_CAMPUS_CAMPAIGN = CampaignSpec(
    campaign_key="cn-2027-ai-product",
    name="国内 2027 AI 产品校招",
    source_platforms=("boss_zhipin",),
    action_strategy=ActionStrategy.BOSS_FIXED_GREETING,
    evaluation_policy_version="boss-rules-v1",
)
GLOBAL_NEW_GRAD_CAMPAIGN = CampaignSpec(
    campaign_key="global-2027-ai-product",
    name="海外 2027 AI 产品 New Grad",
    source_platforms=("linkedin", "company_site"),
    action_strategy=ActionStrategy.TAILORED_APPLICATION,
    evaluation_policy_version="linkedin-rules-v1",
)
BUILTIN_CAMPAIGNS = (CHINA_CAMPUS_CAMPAIGN, GLOBAL_NEW_GRAD_CAMPAIGN)

# Compatibility aliases for call sites that only need the stable database key.
CHINA_CAMPUS_CAMPAIGN_KEY = CHINA_CAMPUS_CAMPAIGN.campaign_key
GLOBAL_NEW_GRAD_CAMPAIGN_KEY = GLOBAL_NEW_GRAD_CAMPAIGN.campaign_key


def campaign_spec_for_platform(platform: str) -> CampaignSpec:
    """Resolve one source platform to its bounded built-in campaign."""

    normalized = platform.strip().casefold()
    for campaign in BUILTIN_CAMPAIGNS:
        if normalized in campaign.source_platforms:
            return campaign
    raise ValueError(f"unsupported campaign source platform: {platform}")
