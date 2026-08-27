"""US LinkedIn new-grad and sponsorship filtering tests."""

from boss_zhipin.domain.job_filter import RuleState
from boss_zhipin.domain.linkedin_filter import evaluate_linkedin_job_rules


def test_2027_new_grad_with_explicit_sponsorship_is_eligible():
    result = evaluate_linkedin_job_rules(
        title="AI Product Manager, University Graduate",
        location="New York, NY",
        description="2027 new grad role. Visa sponsorship is available.",
    )
    assert result.state is RuleState.ELIGIBLE
    assert result.matched_city == "New York"


def test_explicit_no_sponsorship_is_filtered():
    result = evaluate_linkedin_job_rules(
        title="AI Product Manager",
        location="Boston, MA",
        description="2027 new grad. We are unable to sponsor now or in the future.",
    )
    assert result.state is RuleState.FILTERED
    assert "unable to sponsor" in result.reasons[0]


def test_missing_year_or_positive_sponsorship_needs_review():
    missing_year = evaluate_linkedin_job_rules(
        title="AI Product Manager",
        location="Austin, TX",
        description="Entry-level role. Visa sponsorship is available.",
    )
    missing_sponsorship = evaluate_linkedin_job_rules(
        title="AI Product Manager",
        location="San Francisco, CA",
        description="2027 new grad role.",
    )
    assert missing_year.state is RuleState.NEEDS_REVIEW
    assert missing_sponsorship.state is RuleState.NEEDS_REVIEW


def test_senior_or_experienced_role_is_filtered():
    senior = evaluate_linkedin_job_rules(
        title="Senior AI Product Manager",
        location="Washington, DC",
        description="2027. Visa sponsorship is available.",
    )
    experienced = evaluate_linkedin_job_rules(
        title="AI Product Manager",
        location="Washington, DC",
        description="2027 candidates. Requires 5+ years. Visa sponsorship is available.",
    )
    assert senior.state is RuleState.FILTERED
    assert experienced.state is RuleState.FILTERED


def test_wrong_city_or_role_is_filtered():
    wrong_city = evaluate_linkedin_job_rules(
        title="AI Product Manager",
        location="Seattle, WA",
        description="2027 new grad. Visa sponsorship is available.",
    )
    wrong_role = evaluate_linkedin_job_rules(
        title="Machine Learning Engineer",
        location="New York, NY",
        description="2027 new grad. Visa sponsorship is available.",
    )
    assert wrong_city.state is RuleState.FILTERED
    assert wrong_role.state is RuleState.FILTERED


def test_product_manager_with_explicit_ai_context_needs_manual_review():
    result = evaluate_linkedin_job_rules(
        title="Product Manager, Core Models",
        location="San Francisco, CA",
        description="Join OpenAI to shape frontier foundation models.",
    )

    assert result.state is RuleState.NEEDS_REVIEW
    assert result.matched_role.startswith("AI Product Manager")
