# Temporal hierarchies — intraday ↔ daily ↔ macro

Chronos-2 supports forecasting at multiple frequencies in one call —
intraday minute bars, daily closes, weekly macro releases — sharing a
single representation. Use cases this opens up:

- **Intraday liquidity-aware exposure**: replace the end-of-day PFE
  approximation with intraday-aware paths that respect when liquidity
  windows close.
- **Vol-surface forecasting at multiple frequencies**: short-dated
  options driven by intraday flow, long-dated by macro conditioning,
  one consistent forecast.
- **Event-window risk (FOMC, NFP)**: condition on calendar features
  the parametric stack doesn't see; produce event-windowed PFE
  alongside the regular curve.

Like long context, this is a tour beat — not in the live demo, but
named so the audience can recognize where the same deployment pattern
extends.
