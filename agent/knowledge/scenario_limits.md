# Scenario-based limits monitoring

Most limit frameworks compute exposure under a small set of pre-defined
scenarios (parallel rate shifts, FX shocks). Limits breach when computed
exposure exceeds a threshold under any scenario. The framework is
auditable but blind to joint-tail combinations the predefined set does
not enumerate.

A foundation-model overlay generates a continuous scenario manifold,
weighted by the regime detector. The limit framework consumes the
weighted top-N tail paths instead of (or alongside) the predefined set.
The result: limits that adapt to current regime without manual
re-parameterization, with full traceability — every contributing path
is inspectable.
