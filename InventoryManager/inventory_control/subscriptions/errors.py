"""Pure subscription-rule failures without persistence concerns."""

from __future__ import annotations


class SubscriptionRuleError(ValueError):
    """Base class for deterministic subscription-domain rejections."""


class InvalidSeatCountError(SubscriptionRuleError):
    pass


class SeatLimitExceededError(SubscriptionRuleError):
    pass


class InvalidServicePeriodInputError(SubscriptionRuleError):
    pass


class ServicePeriodReductionRejectedError(SubscriptionRuleError):
    """Reduction would end service at or before current database time."""


class ServicePeriodAlreadyExpiredError(SubscriptionRuleError):
    """Expire-now was requested for an already expired period."""
