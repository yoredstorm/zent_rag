# =============================================================================
# Canonical artifacts — frontera entre metadata liviana y vistas grandes
# =============================================================================
# El motor habla con esta tienda. Hoy puede dejar el markdown inline o
# escribirlo junto a los uploads. Mañana se mueve sin tocar el entendimiento.
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path


class CanonicalArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    def place(
        self,
        *,
        organization_id: str,
        document_id: str,
        markdown: str,
        ast: dict,
        max_inline_bytes: int,
    ) -> dict:
        raw_markdown = markdown.encode("utf-8")
        raw_ast = json.dumps(ast, ensure_ascii=False, sort_keys=True).encode("utf-8")
        total = len(raw_markdown) + len(raw_ast)
        if total <= max_inline_bytes or self.root is None:
            return {
                "storage": "inline",
                "overflow": total > max_inline_bytes and self.root is None,
                "markdown": markdown,
                "ast": ast,
                "markdown_bytes": len(raw_markdown),
                "ast_bytes": len(raw_ast),
            }
        folder = self.root / organization_id / "understanding" / document_id
        folder.mkdir(parents=True, exist_ok=True)
        markdown_path = folder / "canonical.md"
        ast_path = folder / "canonical.ast.json"
        markdown_path.write_bytes(raw_markdown)
        ast_path.write_bytes(raw_ast)
        return {
            "storage": "artifact",
            "markdown_ref": str(markdown_path),
            "ast_ref": str(ast_path),
            "markdown_bytes": len(raw_markdown),
            "ast_bytes": len(raw_ast),
        }
