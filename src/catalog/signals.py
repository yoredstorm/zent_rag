# =============================================================================
# Multi-signal column inference — names are signals, never global truth
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

_LEGACY_PREFIX = re.compile(r"^[A-Za-z]\d{3,5}(.+)$")

# Seed lexicon: inference signal only. Never auto-approve.
SEED_LEXICON: dict[str, list[tuple[str, str, float]]] = {
    "DSC": [("Description", "DESCRIPTION", 0.72)],
    "DESC": [("Description", "DESCRIPTION", 0.74)],
    "DES": [("Description", "DESCRIPTION", 0.60)],
    "PRC": [("Unit Price", "MEASURE", 0.70), ("Unit Cost", "MEASURE", 0.52), ("Amount", "MEASURE", 0.18)],
    "PRICE": [("Unit Price", "MEASURE", 0.82)],
    "PREC": [("Unit Price", "MEASURE", 0.70)],
    "CST": [("Unit Cost", "MEASURE", 0.70), ("Unit Price", "MEASURE", 0.30)],
    "COST": [("Unit Cost", "MEASURE", 0.82)],
    "QTY": [("Quantity", "MEASURE", 0.78)],
    "CANT": [("Quantity", "MEASURE", 0.76)],
    "CNT": [("Count", "MEASURE", 0.62)],
    "STK": [("Stock", "MEASURE", 0.78)],
    "STOCK": [("Stock", "MEASURE", 0.84)],
    "FEC": [("Date", "DATE", 0.70)],
    "DT": [("Date", "DATE", 0.55)],
    "DATE": [("Date", "DATE", 0.80)],
    "COD": [("Code", "IDENTIFIER", 0.72)],
    "CD": [("Code", "IDENTIFIER", 0.58)],
    "CODE": [("Code", "IDENTIFIER", 0.80)],
    "CCUST": [("Customer Code", "IDENTIFIER", 0.55)],
    "FPROC": [("Processing Date", "DATE", 0.50)],
    "TRNCU": [("Transaction Type", "STATUS", 0.48)],
    "EST": [("Status", "STATUS", 0.68)],
    "IDCAT": [("Category", "CATEGORY", 0.70)],
    "CODPRD": [("Product Code", "IDENTIFIER", 0.88)],
    "CODCLI": [("Customer Code", "IDENTIFIER", 0.80)],
    "FECREG": [("Registration Date", "DATE", 0.78)],
}

_TYPE_HINTS = (
    (re.compile(r"char|text|clob", re.I), "DESCRIPTION", 0.25),
    (re.compile(r"num|dec|int|float|money|numeric", re.I), "MEASURE", 0.22),
    (re.compile(r"date|time|timestamp", re.I), "DATE", 0.40),
)


@dataclass
class ColumnInference:
    label: str
    role: str
    score: float
    confidence: str
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    signal_scores: dict[str, float] = field(default_factory=dict)
    conflicting: bool = False
    auto_map: bool = False


def tokenize_physical(name: str) -> str:
    raw = (name or "").strip()
    match = _LEGACY_PREFIX.match(raw)
    rest = match.group(1) if match else raw
    return re.sub(r"[_\-\s]+", "", rest).upper()


def confidence_label(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def infer_column(
    *,
    column_name: str,
    table_name: str = "",
    data_type: str = "",
    is_pk: bool = False,
    null_ratio: float | None = None,
    cardinality: int | None = None,
    neighbor_names: list[str] | None = None,
    org_lexicon: dict[str, list[tuple[str, str, float]]] | None = None,
) -> ColumnInference:
    token = tokenize_physical(column_name)
    evidence: list[str] = []
    scores: dict[str, float] = {}
    candidates: dict[str, tuple[str, float]] = {}

    def add(label: str, role: str, score: float, signal: str) -> None:
        prev = candidates.get(label)
        if prev is None or score > prev[1]:
            candidates[label] = (role, score)
        scores[signal] = max(scores.get(signal, 0.0), score)
        if signal not in evidence:
            evidence.append(signal)

    for label, role, score in SEED_LEXICON.get(token, []):
        add(label, role, score, "seed_lexicon")
    for label, role, score in (org_lexicon or {}).get(token, []):
        add(label, role, min(1.0, score + 0.15), "org_lexicon")

    upper_col = column_name.upper()
    for key, entries in SEED_LEXICON.items():
        if key != token and key in upper_col and len(key) >= 3:
            for label, role, score in entries:
                add(label, role, score * 0.7, "name_substring")

    if is_pk or token.startswith("COD") or token.endswith("ID"):
        add("Identifier", "IDENTIFIER", 0.62 if is_pk else 0.50, "pk_or_code")
        evidence.append("unique-ish values" if (cardinality or 0) > 10 else "name pattern")

    for pattern, role, score in _TYPE_HINTS:
        if pattern.search(data_type or ""):
            if role == "DESCRIPTION":
                add("Description", role, score, "data_type")
            elif role == "MEASURE":
                add("Amount", role, score, "data_type")
            elif role == "DATE":
                add("Date", role, score, "data_type")

    neighbors = [n.upper() for n in (neighbor_names or [])]
    if any("COD" in n or n.endswith("ID") for n in neighbors) and token in {"DSC", "DESC", "DES"}:
        add("Description", "DESCRIPTION", 0.88, "neighbor_identifier")
        evidence.append("paired with product description" if False else "neighbor of product code")

    tbl = (table_name or "").upper()
    if "PRD" in tbl or "PROD" in tbl or "ART" in tbl:
        if token in {"DSC", "DESC", "DES"}:
            add("Product Description", "DESCRIPTION", 0.90, "table_context")
        if token == "CODPRD" or token.startswith("COD"):  # noqa: S105 — physical column token, not a secret
            add("Product Code", "IDENTIFIER", 0.92, "table_context")

    if null_ratio is not None and null_ratio < 0.05 and token in {"DSC", "DESC"}:
        add("Description", "DESCRIPTION", 0.15, "null_ratio")

    ranked = sorted(candidates.items(), key=lambda kv: kv[1][1], reverse=True)
    if not ranked:
        return ColumnInference(
            label=column_name,
            role="UNKNOWN",
            score=0.2,
            confidence="low",
            evidence=["no strong signals"],
            auto_map=False,
        )
    top_label, (top_role, top_score) = ranked[0]

    def _same_concept(a: str, b: str) -> bool:
        na, nb = a.lower(), b.lower()
        return na in nb or nb in na

    alts = [(lab, sc[1]) for lab, sc in ranked[1:4]]
    conflict_alts = [
        (lab, sc[1])
        for lab, sc in ranked[1:4]
        if not (sc[0] == top_role and _same_concept(top_label, lab))
    ]
    conflicting = bool(conflict_alts) and (top_score - conflict_alts[0][1]) < 0.25
    overall = min(1.0, top_score)
    if conflicting:
        overall = min(overall, 0.54)
        evidence.append("conflicting evidence")
    conf = confidence_label(overall)
    return ColumnInference(
        label=top_label,
        role=top_role,
        score=round(overall, 3),
        confidence=conf,
        alternatives=alts,
        evidence=evidence,
        signal_scores=scores,
        conflicting=conflicting,
        auto_map=conf == "high" and not conflicting,
    )


def infer_table_entity(table_name: str) -> tuple[str, str, list[str]]:
    token = tokenize_physical(table_name)
    if "PRD" in token or "PROD" in token or "ART" in token:
        return "Product", "high", ["table naming patterns"]
    if "VENT" in token or "SALE" in token:
        return "Sale", "high", ["table naming patterns"]
    if "CUST" in token or "CLI" in token:
        return "Customer", "medium", ["table naming patterns"]
    if token.startswith("A") and any(ch.isdigit() for ch in token[:5]):
        return table_name, "low", ["legacy record name"]
    return table_name.title(), "low", ["table name as-is"]
