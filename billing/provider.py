"""Billing provider seam. The software is free; machine time is the product.

The worker calls report_usage() after every job. The prototype wires
NoopBillingProvider (records locally, charges nothing). Production wires
StripeBillingProvider, which is a deliberate stub: it tells you exactly what
to provide (STRIPE_SECRET_KEY + a metered price) and refuses to guess.

Intended Stripe shape (meter-based billing, no code changes needed elsewhere):
    stripe.billing.MeterEvent.create(
        event_name="conversion_seconds",
        payload={"stripe_customer_id": <id>, "value": str(event.metered_seconds)},
        identifier=event.job_id,   # idempotency
    )
with a Meter aggregating SUM(conversion_seconds) and a Price of
$X per 60 units. See docs/cost-model.md#stripe-metered-billing.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from worker.metering import UsageEvent

log = logging.getLogger("revitbridge.billing")


class BillingProvider(ABC):
    @abstractmethod
    def report_usage(self, event: UsageEvent) -> None:
        """Report one job's metered usage. Must be idempotent per job_id."""


class NoopBillingProvider(BillingProvider):
    """Prototype default: log usage, charge nothing."""

    def __init__(self) -> None:
        self.reported: list[UsageEvent] = []

    def report_usage(self, event: UsageEvent) -> None:
        self.reported.append(event)
        log.info("usage job=%s user=%s backend=%s seconds=%.2f cost_usd=%.4f (noop)",
                 event.job_id, event.user_id, event.backend,
                 event.metered_seconds, event.cost_usd)


class StripeBillingProvider(BillingProvider):
    """Production seam. Not wired: needs STRIPE_SECRET_KEY + metered price id."""

    def __init__(self, api_key: str | None = None,
                 meter_event_name: str = "conversion_seconds") -> None:
        import os

        self.api_key = api_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self.meter_event_name = meter_event_name

    def report_usage(self, event: UsageEvent) -> None:
        raise NotImplementedError(
            "StripeBillingProvider is a seam, not an implementation. To wire it: "
            "1) set STRIPE_SECRET_KEY, 2) create a Billing Meter named "
            f"'{self.meter_event_name}' aggregating SUM of the value field, "
            "3) attach it to a metered Price, 4) replace this method body with the "
            "stripe.billing.MeterEvent.create call documented in this module's "
            "docstring. Until then, use NoopBillingProvider."
        )
