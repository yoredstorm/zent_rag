# Intelligence Calibration

Phase 30B/C — empirical calibration without replacing the deterministic gate.

## Module

`src/intelligence/calibration.py`

- `false_answer_rate` — FP / (TP + FP)
- Confusion matrix: TP / FP / FN / TN
- `empirical_threshold_tune` on `raw_signal_score` samples
- Domain policies: Finance/Legal = strict, Internal FAQ = moderate, Brainstorming = permissive

## Invariant

Policies **never** disable ACL / RBAC / permission controls
(`IMMUTABLE_CONTROLS`).
