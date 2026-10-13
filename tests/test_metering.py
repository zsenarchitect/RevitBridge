import os
import unittest.mock as mock

import pytest

from billing.rates import RateCard, rate_card_from_env
from worker.metering import MemoryUsageLedger, SqliteUsageLedger, UsageEvent


def _event(**kw):
    base = dict(job_id="j1", user_id="u1", backend="aps-cloud", src_fmt="rvt",
                dst_fmt="ifc", input_bytes=100, output_bytes=200,
                metered_seconds=90.0, cost_usd=0.375,
                started_at=1.0, finished_at=91.0)
    base.update(kw)
    return UsageEvent(**base)


def test_rate_card_math():
    card = RateCard()
    assert card.cost_usd("aps-cloud", 90.0) == pytest.approx(0.375)   # 1.5 min @ .25
    assert card.cost_usd("ifcopenshell", 30.0) == pytest.approx(0.01)  # .5 min @ .02
    assert card.cost_usd("mock", 999.0) == 0.0
    assert card.cost_usd("unknown-backend", 60.0) == pytest.approx(0.05)


def test_rate_card_env_override():
    with mock.patch.dict(os.environ, {"RB_RATES_JSON": '{"aps-cloud": 0.99}'}):
        card = rate_card_from_env()
    assert card.cost_usd("aps-cloud", 60.0) == pytest.approx(0.99)
    with mock.patch.dict(os.environ, {"RB_RATES_JSON": "not-json"}):
        with pytest.raises(ValueError):
            rate_card_from_env()


def test_memory_ledger_filter():
    ledger = MemoryUsageLedger()
    ledger.record(_event(job_id="a", user_id="u1"))
    ledger.record(_event(job_id="b", user_id="u2"))
    assert len(ledger.events()) == 2
    assert [e.job_id for e in ledger.events(user_id="u1")] == ["a"]


def test_sqlite_ledger_roundtrip(tmp_path):
    ledger = SqliteUsageLedger(str(tmp_path / "u.db"))
    ledger.record(_event())
    events = ledger.events()
    assert len(events) == 1
    assert events[0].job_id == "j1" and events[0].cost_usd == pytest.approx(0.375)
    assert ledger.events(user_id="nobody") == []
