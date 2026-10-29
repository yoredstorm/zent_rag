# =============================================================================
# P18.2-05/06 — Comprensión por pasajes (propuestas, no conocimiento canónico)
# =============================================================================
# Este módulo NO escribe objetos ni promueve hechos. Deriva, desde los bloques
# estructurados, pasajes abribles y propuestas de personajes/temas/relaciones
# con evidencia textual. La autoridad sigue siendo el compilador y el Evidence
# Ledger; el Explorador las muestra como "detectado, sin verificar".
# =============================================================================
from __future__ import annotations

import re
from collections import Counter, defaultdict

_METHOD = "heuristic-passage-v1"
_MAX_SECTIONS = 12
_MAX_PASSAGES = 10

_SPEECH = (
    r"(?:dijo|dec[ií]a|respondi[oó]|pregunt[oó]|exclam[oó]|susurr[oó]|"
    r"contest[oó]|refut[oó]|pens[oó]|a[nñ]adi[oó]|repuso|insisti[oó]|"
    r"confi[oó]|grit[oó]|murmur[oó]|murmur[oó]|advirti[oó])"
)
_ADVERBS = (
    r"(?:suavemente|t[ií]midamente|entonces|luego|despu[eé]s|al fin|"
    r"m[aá]s tarde|al azar|con aire grave|cort[eé]smente|firmemente|"
    r"enrojeciendo|bostezando|todo confundido|alzando un poco)"
)
_SPEECH_RE = re.compile(_SPEECH, re.IGNORECASE)
_TAIL = re.compile(
    _SPEECH
    + r"\s+(?:"
    + _ADVERBS
    + r"\s+)*(?:(?:el|la|los|las|un|una)\s+)?"
    + r"(?P<name>[a-záéíóúñü]+(?:\s+(?:de\s+)?[a-záéíóúñü]+){0,2})",
    re.IGNORECASE,
)
_LEAD = re.compile(
    _SPEECH
    + r"\s+(?:"
    + _ADVERBS
    + r"\s+)*(?P<who>(?:el|la|los|las)\s+"
    + r"[a-záéíóúñü]+(?:\s+[a-záéíóúñü]+){0,2})\s*$",
    re.IGNORECASE,
)
_TERM = re.compile(
    r"\b(?:el|la|los|las)\s+([a-záéíóúñü]{4,}(?:\s+(?:de\s+)?[a-záéíóúñü]{4,})?)",
    re.IGNORECASE,
)
_DIALOGUE = re.compile(r"[“”«»]|(?:^|\n)\s*[—–-]\s*")
_STOP = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "al",
    "a",
    "y",
    "o",
    "que",
    "en",
    "con",
    "por",
    "para",
    "se",
    "le",
    "les",
    "lo",
    "su",
    "sus",
    "mi",
    "mis",
    "tu",
    "tus",
    "cuando",
    "mientras",
    "pero",
    "porque",
    "entonces",
    "también",
    "tambien",
    "él",
    "ella",
    "ellos",
    "ellas",
    "esto",
    "eso",
    "aquello",
    "todo",
    "todos",
    "toda",
    "todas",
}
_GENERIC_THEMES = {
    "personas",
    "persona",
    "hombres",
    "hombre",
    "mujeres",
    "mujer",
    "niños",
    "niño",
    "niña",
    "día",
    "dias",
    "días",
    "noche",
    "noches",
    "mundo",
    "tierra",
    "cosa",
    "cosas",
    "parte",
    "partes",
    "momento",
    "momentos",
    "vez",
    "veces",
    "modo",
    "manera",
    "lugar",
    "lugares",
    "vida",
    "voz",
    "ojos",
    "mano",
    "manos",
    "cabeza",
    "corazón",
    "corazon",
}
_SKIP_KINDS = {
    "page",
    "page_number",
    "header",
    "footer",
    "figure",
    "caption",
    "section",
}


def _clean_text(value: str) -> str:
    text = (value or "").replace("ﬂ", "fl").replace("ﬁ", "fi")
    text = text.replace("\u00ad", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _usable(text: str) -> bool:
    if len(text) < 25 or len(text) > 4000:
        return False
    if not any(char.isalpha() for char in text):
        return False
    longest = max((len(token) for token in text.split()), default=0)
    return not (longest > 40 and " " not in text[:120])


def _clean_name(value: str) -> str | None:
    text = _clean_text(value).lower()
    text = re.split(r"[.,;:!?—–\"“”«»\n]", text)[0]
    text = re.split(r"\b(?:cuando|mientras|pero|porque|que)\b", text)[0]
    text = re.split(r"\b(?:al|con|sin|en)\b", text)[0]
    text = re.sub(r"^(?:el|la|los|las|un|una)\s+", "", text, flags=re.IGNORECASE)
    words = [word for word in text.split() if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]", word)]
    if not words:
        return None
    if words[0] in _STOP:
        return None
    if any(word in {"cuando", "mientras", "porque"} for word in words):
        return None
    candidate = " ".join(words[:3]).strip()
    if len(candidate) < 3:
        return None
    return candidate


def _merge_prefixes(counts: Counter[str]) -> Counter[str]:
    merged: Counter[str] = Counter(counts)
    for name in sorted(list(merged), key=len, reverse=True):
        if name not in merged:
            continue
        for base in sorted(merged, key=len):
            if base == name or not name.startswith(base + " "):
                continue
            if merged[base] >= 2:
                merged[base] += merged.pop(name)
                break
    return merged


def _structure(blocks: list[dict]) -> list[dict]:
    sections: list[dict] = []
    seen: set[tuple[str, object]] = set()
    ordered = sorted(blocks, key=lambda item: int(item.get("order_index") or 0))
    for index, block in enumerate(ordered):
        if block.get("kind") not in {"section", "heading"}:
            continue
        heading = _clean_text(str(block.get("heading") or block.get("text") or ""))
        if len(heading) < 2:
            continue
        if heading.isdigit():
            continue
        if heading.startswith(("—", "–", "-")) or "?" in heading or "¿" in heading:
            continue
        key = (" ".join(heading.lower().split()), block.get("page_number"))
        if key in seen:
            continue
        seen.add(key)
        excerpt = ""
        for candidate in ordered[index + 1 : index + 8]:
            if candidate.get("kind") in _SKIP_KINDS:
                continue
            value = _clean_text(str(candidate.get("text") or ""))
            if _usable(value):
                excerpt = value[:220]
                break
        sections.append(
            {
                "heading": heading[:180],
                "page": block.get("page_number"),
                "section_path": block.get("section_path") or [],
                "excerpt": excerpt,
                "method": _METHOD,
            }
        )
        if len(sections) >= _MAX_SECTIONS:
            break
    return sections


def _passages(blocks: list[dict], *, narrative_signal: bool) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()
    for block in sorted(blocks, key=lambda item: int(item.get("order_index") or 0)):
        if block.get("kind") not in {"paragraph", "quote", "list_item"}:
            continue
        text = _clean_text(str(block.get("text") or ""))
        if not _usable(text):
            continue
        key = " ".join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        score = 0
        if _SPEECH_RE.search(text):
            score += 3
        if _DIALOGUE.search(text):
            score += 2
        score += min(len(text) / 200, 2)
        candidates.append(
            {
                "passage_id": str(block.get("id") or ""),
                "excerpt": text[:600],
                "page": block.get("page_number"),
                "section_path": block.get("section_path") or [],
                "kind": str(block.get("kind") or "paragraph"),
                "score": round(score, 2),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if narrative_signal:
        candidates = [item for item in candidates if item["score"] >= 2] or candidates
    return candidates[:_MAX_PASSAGES]


def _narrative(blocks: list[dict]) -> dict:
    counts: Counter[str] = Counter()
    pages: dict[str, set] = defaultdict(set)
    excerpt: dict[str, str] = {}
    page_of: dict[str, int | None] = {}
    dialogue_blocks: list[tuple[list[str], str, int | None]] = []

    for block in sorted(blocks, key=lambda item: int(item.get("order_index") or 0)):
        if block.get("kind") not in {"paragraph", "quote", "list_item"}:
            continue
        text = _clean_text(str(block.get("text") or ""))
        if not _usable(text):
            continue
        found: list[str] = []
        for match in _TAIL.finditer(text):
            name = _clean_name(match.group("name"))
            if name:
                found.append(name)
        for match in _LEAD.finditer(text):
            name = _clean_name(match.group("who"))
            if name:
                found.append(name)
        for name in set(found):
            counts[name] += 1
            pages[name].add(block.get("page_number"))
            excerpt.setdefault(name, text[:280])
            page_of.setdefault(name, block.get("page_number"))
        if len(set(found)) >= 2 and _SPEECH_RE.search(text):
            dialogue_blocks.append((sorted(set(found)), text[:280], block.get("page_number")))

    counts = _merge_prefixes(counts)
    participants = []
    for name, mentions in counts.most_common(12):
        if mentions < 2:
            continue
        participants.append(
            {
                "name": name,
                "label": name[:1].upper() + name[1:],
                "mentions": mentions,
                "pages": sorted(page for page in pages[name] if page),
                "page": page_of.get(name),
                "excerpt": excerpt.get(name, ""),
            }
        )

    names = {item["name"] for item in participants}
    theme_counts: Counter[str] = Counter()
    theme_pages: dict[str, set] = defaultdict(set)
    theme_excerpt: dict[str, str] = {}
    theme_page: dict[str, int | None] = {}
    threshold = 2 if sum(len(str(b.get("text") or "")) for b in blocks) < 6000 else 4
    for block in blocks:
        if block.get("kind") != "paragraph":
            continue
        text = _clean_text(str(block.get("text") or ""))
        if not _usable(text):
            continue
        for match in _TERM.finditer(text):
            term = " ".join(match.group(1).lower().split())
            if term in names or term in _STOP or term in _GENERIC_THEMES:
                continue
            if any(term == name or term.startswith(name + " ") for name in names):
                continue
            if len(term) < 4:
                continue
            theme_counts[term] += 1
            theme_pages[term].add(block.get("page_number"))
            theme_excerpt.setdefault(term, text[:280])
            theme_page.setdefault(term, block.get("page_number"))
    themes = [
        {
            "name": name,
            "label": name[:1].upper() + name[1:],
            "mentions": mentions,
            "pages": sorted(page for page in theme_pages[name] if page),
            "page": theme_page.get(name),
            "excerpt": theme_excerpt.get(name, ""),
        }
        for name, mentions in theme_counts.most_common(10)
        if mentions >= threshold
    ]

    relations: list[dict] = []
    for participant in participants[:8]:
        relations.append(
            {
                "subject": participant["label"],
                "predicate": "aparece en",
                "object": f"página {participant['page']}" if participant["page"] else "el documento",
                "evidence_excerpt": participant["excerpt"],
                "page": participant["page"],
                "status": "proposed",
                "claim_kind": "narrative_relation",
                "method": _METHOD,
            }
        )
    for block_names, text, page in dialogue_blocks[:8]:
        if len(block_names) < 2:
            continue
        relations.append(
            {
                "subject": block_names[0],
                "predicate": "dialoga con",
                "object": block_names[1],
                "evidence_excerpt": text,
                "page": page,
                "status": "proposed",
                "claim_kind": "narrative_relation",
                "method": _METHOD,
            }
        )
    return {
        "participants": participants,
        "themes": themes,
        "relations": relations[:20],
        "method": _METHOD,
        "mentions_scanned": sum(counts.values()),
    }


def build_passage_understanding(
    *,
    document: dict | None,
    blocks: list[dict],
    genre: str = "unknown",
) -> dict:
    """Vista estructural y propuestas narrativas derivadas de pasajes."""
    sections = _structure(blocks)
    speech_blocks = sum(
        1
        for block in blocks
        if block.get("kind") in {"paragraph", "quote", "list_item"}
        and _SPEECH_RE.search(_clean_text(str(block.get("text") or "")))
    )
    dialogue_marks = sum(len(_DIALOGUE.findall(_clean_text(str(block.get("text") or "")))) for block in blocks)
    narrative_signal = genre in {"narrative", "educational"} or (speech_blocks >= 3 and dialogue_marks >= 3)
    passages = _passages(blocks, narrative_signal=narrative_signal)
    narrative = (
        _narrative(blocks)
        if narrative_signal
        else {
            "participants": [],
            "themes": [],
            "relations": [],
            "method": _METHOD,
            "mentions_scanned": 0,
        }
    )
    return {
        "method": _METHOD,
        "narrative_signal": narrative_signal,
        "structure": sections,
        "passages": passages,
        "participants": narrative["participants"],
        "themes": narrative["themes"],
        "relations": narrative["relations"],
        "mentions_scanned": narrative["mentions_scanned"],
    }


__all__ = ["build_passage_understanding"]
