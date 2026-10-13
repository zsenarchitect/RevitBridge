import pytest

from billing.provider import BillingProvider, NoopBillingProvider, StripeBillingProvider
from worker.metering import UsageEvent


def _event():
    return UsageEvent(job_id="j1", user_id="u1", backend="ifcopenshell",
                      src_fmt="ifc", dst_fmt="glb", input_bytes=10,
                      output_bytes=20, metered_seconds=2.5, cost_usd=0.001,
                      started_at=1.0, finished_at=3.5)


def test_noop_reports_and_charges_nothing():
    billing = NoopBillingProvider()
    billing.report_usage(_event())  # must not raise
    assert len(billing.reported) == 1


def test_stripe_provider_is_a_seam_not_an_implementation():
    billing = StripeBillingProvider(api_key="sk_test_fake")
    with pytest.raises(NotImplementedError, match="STRIPE_SECRET_KEY"):
        billing.report_usage(_event())


def test_provider_interface():
    assert issubclass(NoopBillingProvider, BillingProvider)
    assert issubclass(StripeBillingProvider, BillingProvider)
