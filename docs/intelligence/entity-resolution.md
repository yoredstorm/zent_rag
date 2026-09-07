# Entity Resolution

Phase 27C governed matching across source systems.

## Domain

`src/core/domain/entity_resolution.py`

- `EnterpriseEntity`, `EntityAlias`, `EntityMatch`
- Statuses: `MATCHED_OBSERVED` | `SUGGESTED_MATCH` | `APPROVED_MATCH` | `REJECTED_MATCH`

## Engine

`src/catalog/entity_resolution.py` — `EntityResolutionEngine`

- `score_match`: exact ids, normalized names, fuzzy (`difflib`)
- `suggest_match`: always `SUGGESTED_MATCH`, never auto-approves

No silent entity merge with business impact.
