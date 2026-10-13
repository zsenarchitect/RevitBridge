# RevitBridge cost model: what conversions cost us vs. what we charge

The software is free and open source. The product is **hosted conversion
machine time**, metered per job. This doc makes the unit economics explicit.
Treat the $ figures as working estimates — re-verify before pricing goes live.

## Our cost per conversion-minute, by backend

| Backend | Infra | Our cost (est.) | Notes |
|---|---|---|---|
| `ifcopenshell` | Cheap Linux VM/VPS (~$6–12/mo → ~$0.01/hr) | **~$0.0002/min** | IFC→mesh is CPU-bound tessellation; no license cost |
| `local-revit` | Windows VM, 4 vCPU/16 GB (~$0.15–0.30/hr on-demand) + Revit license amortized | **~$0.005/min** + license | Revit license cost per worker: **TBD — verify current Autodesk terms for headless/server use** |
| `aps-cloud` | Autodesk's cloud, not ours | **~$0.10/min** | APS Design Automation bills 6 Cloud Credits/hr for the Revit engine; Autodesk's own worked example puts 1 min ≈ $0.10 ([source](https://aps.autodesk.com/blog/estimate-design-automation-costs)). Verify current pricing — Autodesk is migrating to Flex tokens. |
| `mock` | — | $0 | never billed |

Add ~1 min of transfer overhead per APS job (their docs: ~30s up + ~30s down).

## Worked examples

| Job | Backend | Time | Our cost | We charge | Margin |
|---|---|---|---|---|---|
| House IFC → GLB | ifcopenshell | ~45s | ~$0.0002 | $0.015 (1 min @ $0.02/min, rounded up) | ~75x |
| 200 MB RVT → IFC → GLB | aps-cloud + ifcopenshell | ~4 min APS + 1 min local | ~$0.40 | $1.25 (5 min @ $0.25/min) | ~3x |
| RVT → IFC, small model | local-revit | ~2 min | ~$0.01 + license slice | $0.20 (2 min @ $0.10/min) | ~20x |

Billing granularity: per-second metering, per-minute rounding **up** (1s job = 1 min charge). This is standard for the category and keeps micropayments sane.

## Pricing to users (draft)

- **Free tier:** 15 conversion-minutes/month, no card required. Enough to convert a real project once or twice — the funnel.
- **Pay as you go:** metered per conversion-minute at the rate card (`billing/rates.py`).
- **Credit packs (later):** prepay minutes at a volume discount; credits never expire.

The free tier costs us almost nothing (ifcopenshell jobs are sub-cent) and every
paid RVT job subsidizes hundreds of free IFC jobs. That asymmetry is the business.

## Stripe metered billing design

Status: **seam, not implementation** (`billing/provider.py:StripeBillingProvider`).

1. Create a Stripe **Billing Meter** with event name `conversion_seconds`,
   aggregation `SUM`, measuring the `value` field.
2. Create a **metered Price**, e.g. $0.02 per 60 units (= per conversion-minute).
3. On each `UsageEvent`, the worker calls `report_usage()`:
   `stripe.billing.MeterEvent.create(event_name="conversion_seconds",
   payload={"stripe_customer_id": ..., "value": str(seconds)},
   identifier=job_id)` — `identifier` gives idempotency per job.
4. The usage ledger (`worker/metering.py`) is the source of truth; if a meter
   event fails, replay from the ledger. Billing must never lose a job record,
   and a billing failure must never fail a conversion (see `worker/pool.py`).

Wire-up checklist lives in `billing/provider.py:StripeBillingProvider.report_usage`.
Do not start here until: STRIPE_SECRET_KEY issued, meter + price created in
test mode, and the rate card above is finalized.

## What could break the model

- **Revit licensing for headless workers.** The biggest unknown. If Autodesk
  requires a full per-machine subscription for server-side Revit, `local-revit`
  gets expensive fast and APS becomes the default RVT path. Resolve before
  promising RVT SLAs.
- **APS price changes.** Our margin on `aps-cloud` is thinnest; pin the rate
  card to verified current pricing quarterly.
- **Abuse of the free tier.** Rate-limit by IP/API key; the free tier is a
  funnel, not a public compute charity.
