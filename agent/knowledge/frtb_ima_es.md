# FRTB IMA expected shortfall augmentation

FRTB Internal Model Approach centers on an Expected Shortfall calculation
under stress-period calibration. The challenge is that "stress period"
selection is often a backward-looking exercise picking a single window;
correlation-breakdown effects are baked into that window's empirical
covariance, with no mechanism for new regime structure.

A foundation-model overlay augments the stressed-ES path set with paths
conditioned on FM-detected current-regime features. The reweighter keeps
the regulatory ES anchor (uniform-weight historical) while shifting tail
mass toward augmented paths when the regime detector indicates stress.
This is a challenger ES, useful for internal capital adequacy oversight
even where the regulatory ES is unchanged.
