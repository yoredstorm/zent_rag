# =============================================================================
# Data Onboarding — extracción de hechos en documentos (reglas + LLM opcional)
# =============================================================================
# Reglas deterministas para fechas, montos, partes, RUT, correos y cláusulas.
# LLM opcional (si hay provider y no estamos en test) complementa con cláusulas
# y pares clave/valor. El LLM nunca bloquea: si falla, quedan las reglas.
# =============================================================================
from __future__ import annotations

import json
import re
from io import BytesIO

from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.normalize.base import get_normalizer

logger = get_logger(__name__)

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

_FORBIDDEN_DATE_CTX = (
    "numero", "número", "no.", "nro", "folio", "clausula", "cláusula", "literal", "art.", "articulo",
)

_RUT_RE = re.compile(r"(?<!\d)([0-9]{1,2}\.[0-9]{3}\.[0-9]{3}[-−][0-9kK])(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")


def _fact(
    fact_type: str,
    key: str,
    value: str,
    *,
    evidence: str = "",
    page: int | None = None,
    confidence: str = "medium",
    normalized_value: str | None = None,
    source: str = "rules",
) -> dict:
    return {
        "fact_type": fact_type,
        "key": key,
        "value": value,
        "normalized_value": normalized_value,
        "evidence": evidence[:220],
        "page": page,
        "confidence": confidence,
        "source": source,
    }


def _normalize_text(data: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    try:
        normalizer = get_normalizer(ext)
        if normalizer is not None:
            text = normalizer.normalize(data, source_name=filename)
            if text and text.strip():
                return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("document normalize failed", error=str(exc)[:200])
    return data[:8000].decode("utf-8", errors="replace")


def _page_count(data: bytes, filename: str) -> int | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    if ext != "pdf":
        return None
    try:
        from pdfminer.pdfpage import PDFPage

        return sum(1 for _ in PDFPage.get_pages(BytesIO(data)))
    except Exception:  # noqa: BLE001
        return None


def _window(text: str, start: int, size: int = 120) -> str:
    return text[max(0, start - 40): start + size]


def _normalize_date(match: re.Match) -> str | None:
    groups = match.groups()
    try:
        a_s, b_s, c_s = groups[0], groups[1].lower(), groups[2]
        if b_s in _MONTHS and a_s.isdigit() and c_s.isdigit():
            return f"{int(c_s):04d}-{_MONTHS[b_s]:02d}-{int(a_s):02d}"
        if a_s.isdigit() and b_s.isdigit() and c_s.isdigit():
            a, b, c = int(a_s), int(b_s), int(c_s)
            if c > 1900 and a <= 31 and b <= 12:  # d/m/Y
                return f"{c:04d}-{b:02d}-{a:02d}"
            if a > 1900 and b <= 12 and c <= 31:  # YYYY-mm-dd
                return f"{a:04d}-{b:02d}-{c:02d}"
            if a <= 31 and b <= 12 and c <= 99:  # d/m/yy
                return f"{2000 + c:04d}-{b:02d}-{a:02d}"
    except (TypeError, ValueError, IndexError):
        return None
    return None


_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})\b", re.IGNORECASE),
]

_DATE_CONTEXT = (
    ("firma", "Fecha de firma"),
    ("inicio", "Fecha de inicio"),
    ("desde", "Fecha de inicio"),
    ("término", "Fecha de término"),
    ("termino", "Fecha de término"),
    ("hasta", "Fecha de término"),
    ("vencim", "Fecha de vencimiento"),
    ("expira", "Fecha de expiración"),
    ("renovac", "Fecha de renovación"),
    ("prórrog", "Fecha de prórroga"),
    ("prorrog", "Fecha de prórroga"),
    ("vigencia", "Inicio de vigencia"),
    ("entrega", "Fecha de entrega"),
)


def _classify_date(text: str, pos: int) -> str:
    best = "Fecha"
    best_dist = 10**9
    low = text.lower()
    for keyword, label in _DATE_CONTEXT:
        start = 0
        while True:
            idx = low.find(keyword, start)
            if idx == -1:
                break
            start = idx + len(keyword)
            distance = abs(idx - pos)
            if distance <= 120 and distance < best_dist:
                best = label
                best_dist = distance
    return best


def _extract_dates(text: str) -> list[dict]:
    facts: list[dict] = []
    seen: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            normalized = _normalize_date(match)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            ctx = _window(text, match.start(), size=100).lower()
            if any(k in ctx for k in _FORBIDDEN_DATE_CTX):
                continue
            key = _classify_date(text, match.start())
            facts.append(
                _fact(
                    "date",
                    key,
                    normalized,
                    normalized_value=normalized,
                    evidence=text[max(0, match.start() - 60): match.end() + 40],
                    confidence="high",
                )
            )
    return facts


_AMOUNT_KW = (
    "monto", "tarifa", "precio", "honorario", "pag", "abon", "comision", "comisión",
    "canon", "cánon", "renta", "arancel", "mensual", "anual", "sueldo", "remuneración",
    "remuneracion", "fee", "salary", "monthly", "annual",
)
_AMOUNT_RE = re.compile(
    r"(?:(CLP|USD|UF|EUR|MXN|ARS|PEN|UYU|BRL)\s*)?([\d][\d.,]{1,18})(?:\s*(CLP|USD|UF|EUR|MXN|ARS|PEN|UYU|BRL|dólares|dolares|pesos|euros))?",
    re.IGNORECASE,
)
_PERIOD_KW = (
    "mensual", "por mes", "al mes", "cada mes", "mensualmente",
    "anual", "por año", "al año", "por a\u00f1o", "annual",
    "semanal", "por semana", "diario", "por día", "por dia",
)


def _extract_amounts(text: str) -> list[dict]:
    facts: list[dict] = []
    seen: set[str] = set()
    for keyword in _AMOUNT_KW:
        for match in re.finditer(keyword, text, re.IGNORECASE):
            # Solo mira hacia adelante: evita números de párrafos anteriores.
            ctx = text[match.end(): match.end() + 180]
            amount_match = _AMOUNT_RE.search(ctx)
            if not amount_match:
                continue
            raw = amount_match.group(2)
            currency = (amount_match.group(1) or amount_match.group(3) or "").upper()
            if raw in seen:
                continue
            seen.add(raw)
            ctx_lower = ctx.lower()
            period = "único"
            for pw in _PERIOD_KW:
                if pw in ctx_lower:
                    period = pw
                    break
            if currency in ("DÓLARES", "DOLARES"):
                currency = "USD"
            key = f"Monto ({currency})" if currency else "Monto"
            if period != "único":
                key = f"{key} {period.capitalize()}"
            facts.append(
                _fact(
                    "amount",
                    key,
                    f"{currency} {raw}".strip(),
                    normalized_value=raw.replace(".", "").replace(",", "."),
                    evidence=ctx.strip()[:220],
                    confidence="high" if currency else "medium",
                )
            )
    return facts


def _clean_party_name(raw: str) -> str | None:
    name = re.sub(r"^\s*(?:y\s+|e\s+|& )", "", (raw or "").strip())
    if not name:
        return None
    for stop in (" por una parte", " por la otra", " en adelante", " con domicilio", " desde hoy"):
        idx = name.lower().find(stop)
        if idx != -1:
            name = name[:idx].strip()
            break
    if not name:
        return None
    if name[0].isupper():
        return name
    match = re.search(
        r"\b[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜ&.]*(?:\s+[\wÁÉÍÓÚÑÜ&.-]+){0,4}", name
    )
    return match.group(0).strip() if match else None


def _extract_parties(text: str) -> list[dict]:
    facts: list[dict] = []
    party_union_re = re.compile(
        r"entre\s+([A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜ&.]*(?:\s+[\wÁÉÍÓÚÑÜ&.-]+){0,5})",
        re.IGNORECASE,
    )
    party_a = party_union_re.search(text)
    if party_a:
        name = _clean_party_name(party_a.group(1))
        if name:
            facts.append(
                _fact(
                    "party",
                    "Parte A",
                    name,
                    evidence=" ".join(text[max(0, party_a.start()): party_a.start() + 140].split()),
                    confidence="medium",
                )
            )
    party_b_re = re.compile(
        r"([A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜ&.]*(?:\s+[\wÁÉÍÓÚÑÜ&.-]+){0,5})\s*,\s*por la otra parte",
        re.IGNORECASE,
    )
    party_b = party_b_re.search(text)
    if party_b:
        name = _clean_party_name(party_b.group(1))
        if name and (not party_a or name != _clean_party_name(party_a.group(1))):
            facts.append(
                _fact(
                    "party",
                    "Parte B",
                    name,
                    evidence=" ".join(text[max(0, party_b.start() - 60): party_b.start() + 30].split()),
                    confidence="medium",
                )
            )
    return facts


_CLAUSE_HEADINGS = (
    "renovac", "prórrog", "prorrog", "térm", "term", "confidencial", "obligac",
    "pago", "indemniz", "rescis", "penal", "cesión", "cesion", "garant",
    "sancion", "sanción", "cumplimiento",
)


def _extract_clauses(text: str, headings: list[str]) -> list[dict]:
    facts: list[dict] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for heading in headings:
        haystack = (heading or "").lower()
        if not any(k in haystack for k in _CLAUSE_HEADINGS):
            continue
        if heading.strip().lower() in seen:
            continue
        seen.add(heading.strip().lower())
        following = ""
        idx = next((i for i, ln in enumerate(lines) if heading.strip() in ln), None)
        if idx is not None:
            following = " ".join(
                ln.strip() for ln in lines[idx + 1: idx + 4] if ln.strip()
            )[:200]
        facts.append(
            _fact(
                "clause",
                f"Cláusula de {heading.strip().title()}",
                heading.strip(),
                evidence=(f"{heading.strip()} — {following}").strip()[:220],
                confidence="medium",
            )
        )
    return facts


def _extract_identifiers(text: str) -> list[dict]:
    facts: list[dict] = []
    for match in _RUT_RE.finditer(text):
        facts.append(
            _fact(
                "identifier",
                "RUT",
                match.group(1),
                normalized_value=match.group(1),
                evidence=text[max(0, match.start() - 50): match.start() + 20],
                confidence="high",
            )
        )
    for match in _EMAIL_RE.finditer(text):
        facts.append(
            _fact(
                "identifier",
                "Correo",
                match.group(0),
                evidence=text[max(0, match.start() - 40): match.start() + 20],
                confidence="high",
            )
        )
    return facts


def _dedupe(facts: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in facts:
        dedupe_key = (fact["fact_type"], fact["key"], fact["value"])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(fact)
    return out


def _headings(text: str) -> list[str]:
    headings = re.findall(r"^#{1,3}\s+(.+)$", text, flags=re.M)
    if not headings:
        headings = [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and ln.strip() == ln.strip().upper() and 3 < len(ln.strip()) < 80
        ][:12]
    if len(headings) < 3:
        numbered = re.findall(
            r"(?im)^\s*(?:[0-9A-ZÁÉÍÓÚÑ]+)\s*[.:]\s*([^\n]{3,90})$", text
        )
        headings = (headings + [h.strip() for h in numbered])[:20]
    return headings[:20]


async def _llm_facts(text: str) -> list[dict]:
    import os

    from src.core.config import get_settings

    settings = get_settings()
    if settings.ENVIRONMENT == "test" or os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    if not (settings.LITELLM_API_KEY or settings.LITELLM_API_BASE):
        return []
    try:
        from src.api.deps import get_llm_provider

        prompt = (
            "Extrae datos clave de este documento en JSON. Devuelve SOLO un array JSON "
            'de objetos con: "type" (party|date|amount|clause|identifier), "key" '
            '(etiqueta corta en español, ej: "Contratante", "Fecha de renovación"), '
            '"value" (valor exacto), "confidence" (high|medium|low). '
            "Máximo 20 items. Sin texto ajeno. Documento:\n\n"
            + text[:12000]
        )
        response = await get_llm_provider().generate(
            prompt, max_tokens=1200, temperature=0.0
        )
        content = (response.content or "").strip()
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        raw = json.loads(content[start:end + 1])
        facts: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            ftype = str(item.get("type") or "fact")
            key = str(item.get("key") or "Dato")
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            facts.append(
                _fact(
                    ftype,
                    key,
                    value,
                    confidence=str(item.get("confidence") or "medium"),
                    source="llm",
                )
            )
        return facts
    except Exception as exc:  # noqa: BLE001
        logger.warning("document llm facts failed", error=str(exc)[:200])
        return []


def _merge_facts(rules: list[dict], llm: list[dict]) -> list[dict]:
    merged = list(rules)
    seen = {(f["fact_type"], f["key"], f["value"].lower()) for f in rules}
    rule_party_values = [
        f["value"].lower() for f in rules if f["fact_type"] == "party"
    ]
    for fact in llm:
        if (fact["fact_type"], fact["key"], fact["value"].lower()) in seen:
            continue
        # LLM solo complementa; evita partes que ya detectaron las reglas.
        if fact["fact_type"] == "party" and any(
            fv == fv2 or fv in fv2 or fv2 in fv
            for fv in rule_party_values
            for fv2 in (fact["value"].lower(),)
        ):
            continue
        merged.append(fact)
        seen.add((fact["fact_type"], fact["key"], fact["value"].lower()))
    return merged


async def extract_document_facts(data: bytes, filename: str) -> dict:
    """Extrae hechos de un documento. Devuelve perfil con hechos y metadatos."""
    text = _normalize_text(data, filename)
    rules: list[dict] = []
    rules.extend(_extract_parties(text))
    rules.extend(_extract_dates(text))
    rules.extend(_extract_amounts(text))
    rules.extend(_extract_identifiers(text))
    rules.extend(_extract_clauses(text, _headings(text)))
    rules = _dedupe(rules)
    llm = await _llm_facts(text)
    return {
        "pages": _page_count(data, filename),
        "text_ok": bool(text.strip()),
        "text_len": len(text),
        "headings": _headings(text)[:20],
        "facts": _merge_facts(rules, llm),
    }
