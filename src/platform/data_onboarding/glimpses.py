# =============================================================================
# Data Onboarding — glimpses y percent para el paso Analizar
# =============================================================================
from __future__ import annotations

TERMINAL = frozenset({"REVIEW_REQUIRED", "TESTING", "READY", "NEEDS_ATTENTION"})
MAX_GLIMPSES = 12


def analyze_percent(
    phases: list[dict],
    status: str | None,
    job_progress: float | int | None = None,
) -> int:
    if status in TERMINAL:
        return 100
    total = len(phases)
    done = sum(1 for p in phases if p.get("state") == "done")
    phase_pct = (done / total) * 100 if total else 0.0
    if isinstance(job_progress, (int, float)):
        job = min(max(float(job_progress), 0.0), 100.0)
        raw = (phase_pct + job) / 2
    else:
        raw = phase_pct
    if status in ("ANALYZING", "DISCOVERING") and not isinstance(job_progress, (int, float)):
        raw = min(raw, 90.0)
    return int(round(min(max(raw, 0.0), 100.0)))


def _fact_text(fact: dict) -> str | None:
    key = str(fact.get("key") or "").strip()
    value = str(fact.get("value") or "").strip()
    if not value:
        return None
    ftype = str(fact.get("fact_type") or "").lower()
    if ftype in ("party", "identifier"):
        return f"Ah, {key} es {value}" if key else f"Ah, {value}"
    if ftype == "amount":
        return f"Vi un monto: {value}"
    if ftype == "date":
        return f"Fecha: {value}"
    if ftype == "clause":
        return f"{value[:77]}…" if len(value) > 80 else value
    if key:
        return f"{key}: {value}"
    return value


def build_glimpses(understanding: dict) -> list[dict]:
    out: list[dict] = []
    facts = understanding.get("facts") or []
    if facts:
        for i, fact in enumerate(facts):
            if len(out) >= MAX_GLIMPSES:
                break
            text = _fact_text(fact)
            if not text:
                continue
            key = str(fact.get("key") or fact.get("fact_type") or i)
            out.append({"id": f"fact-{i}-{key}", "text": text})
        return out
    entity = str(understanding.get("likely_entity") or "").strip()
    if entity:
        out.append({"id": "entity", "text": f"Esto parece {entity}"})
    for i, ent in enumerate(understanding.get("entities") or []):
        if len(out) >= MAX_GLIMPSES:
            break
        name = str((ent or {}).get("name") or "").strip()
        if name:
            out.append({"id": f"ent-{i}", "text": f"Esto parece {name}"})
    for i, col in enumerate(understanding.get("columns") or []):
        if len(out) >= MAX_GLIMPSES:
            break
        name = str((col or {}).get("physical_name") or "").strip()
        if name:
            out.append({"id": f"col-{i}-{name}", "text": f"Columna {name}…"})
    return out[:MAX_GLIMPSES]
