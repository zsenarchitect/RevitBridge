"""Rate card: what we charge per conversion-minute, per backend.

Defaults are grounded in docs/cost-model.md (our infra cost + margin).
Override via RB_RATES_JSON='{"aps-cloud": 0.30}' or by constructing
RateCard directly. All money math lives here, in one place.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class RateCard:
    """USD charged per conversion-minute of worker machine time."""
    usd_per_minute: dict[str, float] = field(default_factory=lambda: {
        # ifcopenshell: cheap Linux worker (~$0.02/hr infra) + margin
        "ifcopenshell": 0.02,
        # local-revit: Windows VM + Revit license amortized
        "local-revit": 0.10,
        # aps-cloud: APS bills ~$0.10/min for the Revit engine; we add margin
        "aps-cloud": 0.25,
        # mock: pipeline smoke tests are free
        "mock": 0.0,
        # auto: resolved to the backend actually used before billing
        "auto": 0.05,
    })
    default_per_minute: float = 0.05
    currency: str = "usd"

    def cost_usd(self, backend: str, metered_seconds: float) -> float:
        rate = self.usd_per_minute.get(backend, self.default_per_minute)
        return round(metered_seconds / 60.0 * rate, 4)


def rate_card_from_env() -> RateCard:
    raw = os.environ.get("RB_RATES_JSON", "")
    if not raw:
        return RateCard()
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"RB_RATES_JSON is not valid JSON: {e}") from e
    card = RateCard()
    card.usd_per_minute.update({k: float(v) for k, v in overrides.items()})
    return card
