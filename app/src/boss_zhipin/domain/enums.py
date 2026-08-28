"""Small domain enums shared by persistence and application services."""

from __future__ import annotations

from enum import StrEnum


class ReviewState(StrEnum):
    """Human decision for one outreach draft."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    """Decisions accepted by the review workflow."""

    APPROVE = "approve"
    REJECT = "reject"
