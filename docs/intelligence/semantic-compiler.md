# Zent Semantic Compiler

Phase 26 foundation for Enterprise Semantic Intelligence.

## 26A — Concept classification (implemented)

Natural-language concepts are classified into formal `BusinessObjectType` values
**before** Answerability decides `CONTEXT_MISSING`.

```text
Question
  → Query Understanding (extract concepts)
  → ConceptClassifier
  → concept_types + requires_definition
  → Planner / Evidence / Answerability Gate
```

### Business object types

| Type | Role | Forces definition? |
|------|------|--------------------|
| `ENTITY` | customer, product, order | No |
| `FACT` | sale, return | No |
| `DIMENSION` | region, channel | No |
| `MEASURE` | amount, quantity | No |
| `DERIVED_METRIC` | margin, net_sales | **Yes** |
| `BUSINESS_RULE` | active / profitable customer | **Yes** |
| `BUSINESS_TERM` | premium, priority | **Yes** |
| `SEGMENT` | corporate | **Yes** |
| `ENUM` | status codes | No |
| `TIME_DIMENSION` / `CURRENCY` / `UNIT` / `FILTER` | reserved | No (unless later rules) |

Unknown tokens default to `ENTITY`. They never auto-require a definition.
Intent `concept_definition` may promote unknowns to `BUSINESS_TERM`.

### When `CONTEXT_MISSING` fires

Only concepts in `understanding.requires_definition` (types in
`DEFINITIONAL_TYPES`) that are unresolved against approved business
definitions. LLM extraction alone does **not** make every noun definitional.

Key modules:

- `src/core/domain/semantic.py` — `BusinessObjectType`, `DEFINITIONAL_TYPES`
- `src/intelligence/concept_classification.py` — `ConceptClassifier`
- `src/intelligence/understanding.py` — wires classifier into deterministic + LLM merge
- `src/intelligence/answerability.py` — uses `requires_definition` only

### Principles

```text
LLM inference != truth
No evidence != answer
Basic ENTITY/FACT != missing business definition
```

## Planned (not in 26A)

- **26B** Business Semantic AST + compiler IR
- **26C** Verified Query Repository
- **26D** Verified Query ↔ SQL Expert
- Hybrid catalog search, entity resolution, temporal semantics, analytical
  research plans, and calibration — see phases 27–30 roadmap
