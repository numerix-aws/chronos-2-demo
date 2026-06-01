# Market data gap-filling for stale or sparse series

Emerging-market FX, off-the-run rates, and infrequently quoted credit
spreads have stale or missing observations. Today these gaps are filled
with proxy series, last-observation-carry-forward, or PCA reconstruction
from correlated liquid factors — all of which lose information about
joint dynamics during stress windows when the proxies themselves break.

A time-series FM trained on dense markets transfers across to sparse
ones by conditioning on observable cross-asset features. Plan A's
covariate channel (VIX/MOVE/WTI) demonstrates the mechanism; the same
trick fills, e.g., a stale TRY rate using observed EUR rates, USDTRY,
and oil futures, with explicit uncertainty bands rather than a fitted
deterministic value.
