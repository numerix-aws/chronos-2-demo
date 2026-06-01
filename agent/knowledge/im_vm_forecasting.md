# Initial Margin / Variation Margin forecasting

IM and VM forecasts depend on quantile estimates of future P&L
distributions, conditioned on the current portfolio and on the joint
evolution of risk factors. Today these are typically driven by historical
simulation or filtered historical simulation — a path set with
no regime awareness.

A time-series FM contributes a probabilistic joint forecast keyed off
the same lookback window, with two practical advantages: covariate
awareness (VIX, MOVE, basis swap spreads) and explicit conditioning on
analyst-supplied stress narratives. The same blender + reweighter that
Plan A builds for PFE applies — IM/VM is a different read on the same
weighted path tensor.
