# Long context windows — multi-cycle conditioning

Chronos-2's long context window admits multi-decade conditioning history
in a single forward pass — useful when the regime is not adequately
characterized by a 60-day rolling window. Examples:

- 2022 rate-hike conditioning is sharper when the model can attend to
  1994 and 1979 cycles, not just trailing 12 months.
- FX peg breaks are rare events; long-context conditioning exposes
  pre-break statistical signatures (vol-of-vol drift, basis widening)
  invisible to short-window detectors.
- Decade-spanning backtests run without rolling recalibration — the
  model is the calibration.

This capability is **not** exercised in the live demo (we use a 60-day
context window for parity with the parametric baseline); it is one of
the "what else could this enable" beats for the closing tour.
