# Stress test design (regulatory + internal)

Time-series foundation models help two ways: scenario library curation
(which historical regimes are actually distinct?) and forward stress
construction (generate plausible but unseen joint stress paths conditioned
on macro narratives). Where parametric calibration forces a single
covariance assumption per regime, an FM samples joint paths whose
correlation structure varies path-by-path, exposing tail-coupling regimes
classical methods miss.

The Plan A "correct + reweight" pattern transfers directly: keep your
existing regulatory stress tests as the parametric anchor; let the FM
generate an augmented overlay; report sensitivity to the augmentation.
The augmented set is not the regulatory submission — it is the
challenger model that flags where the submission may be optimistic.
