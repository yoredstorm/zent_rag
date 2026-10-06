# =============================================================================
# P0 — Visual debug: por qué un parser adquirió o perdió conocimiento
# =============================================================================
# HTML autocontenido por documento: bboxes A/B por página, bloques, unidades
# semánticas y reglas canónicas de cada lado + resumen del KnowledgeDiff.
# =============================================================================
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from src.knowledge.parser_lab.p0.state import KnowledgeState

_COLORS = {
    "heading": "#1d4ed8",
    "paragraph": "#374151",
    "table": "#b45309",
    "list": "#047857",
    "figure": "#7c3aed",
    "formula": "#be123c",
    "default": "#6b7280",
}


def _svg(document, *, label: str) -> str:
    width, height = 612.0, 792.0
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="300" height="388" '
        f'style="border:1px solid #ddd;background:#fff">',
        f'<text x="8" y="16" font-size="12" fill="#111">{html.escape(label)}</text>',
    ]
    for block in document.blocks:
        bbox = block.bbox
        if bbox is None:
            continue
        color = _COLORS.get(block.kind.value, _COLORS["default"])
        parts.append(
            f'<rect x="{bbox.x0:.1f}" y="{bbox.y0:.1f}" '
            f'width="{max(bbox.x1 - bbox.x0, 1):.1f}" '
            f'height="{max(bbox.y1 - bbox.y0, 1):.1f}" '
            f'fill="none" stroke="{color}" stroke-width="0.8" opacity="0.7"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _block_list(document, *, limit: int = 40) -> str:
    rows = []
    for block in list(document.blocks)[:limit]:
        text = html.escape((block.text or "")[:120])
        rows.append(
            f"<li><code>{block.kind.value}</code> p{block.page} "
            f"<span>{text}</span></li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def _unit_list(state: KnowledgeState, *, limit: int = 40) -> str:
    rows = []
    for unit in list(state.units)[:limit]:
        rows.append(
            f"<li><code>{html.escape(str(getattr(unit, 'unit_type', '')))}</code> "
            f"<span>{html.escape((getattr(unit, 'content', '') or '')[:140])}</span></li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def _rule_list(state: KnowledgeState, *, limit: int = 30) -> str:
    rows = []
    for rule in list(state.rules)[:limit]:
        rows.append(
            f"<li><code>{html.escape(str(getattr(rule, 'verification_state', '')))}"
            f"{'/EXEC' if getattr(rule, 'executable', False) else ''}</code> "
            f"<span>{html.escape((getattr(rule, 'statement', '') or '')[:160])}</span></li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def write_visual_debug(
    path: str | Path,
    *,
    golden: dict[str, Any],
    state_a: KnowledgeState,
    state_b: KnowledgeState,
    diff: dict[str, Any],
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pages = max(state_a.document.page_count, state_b.document.page_count, 1)
    page_sections = []
    for page in range(1, pages + 1):
        blocks_a = [b for b in state_a.document.blocks if b.page == page]
        blocks_b = [b for b in state_b.document.blocks if b.page == page]
        doc_a = _slice(state_a.document, blocks_a)
        doc_b = _slice(state_b.document, blocks_b)
        page_sections.append(
            f"<h3>Página {page}</h3><div style='display:flex;gap:12px'>"
            f"{_svg(doc_a, label=f'A: {state_a.label}')}"
            f"{_svg(doc_b, label=f'B: {state_b.label}')}</div>"
        )
    diff_summary = html.escape(json.dumps(diff.get("counts") or {}, ensure_ascii=False))
    body = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Visual debug — {html.escape(str(golden.get('document')))}</title></head>
<body style="font-family:system-ui,sans-serif;margin:24px">
<h1>{html.escape(str(golden.get('title') or golden.get('document')))}</h1>
<p><strong>Golden objects:</strong> {len(golden.get('objects') or [])} ·
<strong>KnowledgeDiff:</strong> <code>{diff_summary}</code></p>
{''.join(page_sections)}
<div style="display:flex;gap:24px;flex-wrap:wrap">
<div style="flex:1;min-width:360px"><h2>A: {html.escape(state_a.label)}</h2>
<h3>Bloques</h3>{_block_list(state_a.document)}
<h3>Unidades</h3>{_unit_list(state_a)}
<h3>Reglas canónicas</h3>{_rule_list(state_a)}</div>
<div style="flex:1;min-width:360px"><h2>B: {html.escape(state_b.label)}</h2>
<h3>Bloques</h3>{_block_list(state_b.document)}
<h3>Unidades</h3>{_unit_list(state_b)}
<h3>Reglas canónicas</h3>{_rule_list(state_b)}</div>
</div>
</body></html>"""
    target.write_text(body, encoding="utf-8")
    return str(target)


def _slice(document, blocks):
    import dataclasses

    return dataclasses.replace(document, blocks=tuple(blocks))


__all__ = ["write_visual_debug"]
