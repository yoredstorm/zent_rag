# Temporal Semantics

Phase 28A — effective dating + Spanish time phrases.

## Module

`src/intelligence/temporal.py` — `TemporalResolver`

- `resolve_version(objects_with_effective_from_to, as_of)` picks the definition
  valid at the requested date (`effective_from` / `effective_to`).
- `parse_time_phrase` supports: hoy, ayer, esta semana, mes pasado, Q1–Q4, YTD, MTD, etc.

## Fix

`"hoy"` alone resolves to **current**, not past.
