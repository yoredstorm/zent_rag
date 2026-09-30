# =============================================================================
# Evaluación local de Document Understanding. Sin LLM. Sin OCR. Sin visión.
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from src.knowledge.structure.pdf_parser import PdfParseOptions, PdfParser
from src.knowledge.understanding.diagnose import (
    diagnose_question,
    find_literal,
    regression_gate,
    score_expected,
)
from src.knowledge.understanding.engine import file_sha256, understand_document
from src.knowledge.understanding.units import chunks_for_document


def evaluate(path: Path, *, find: str | None = None, query: str | None = None) -> dict:
    data = path.read_bytes()
    parsed = PdfParser().parse(
        data,
        organization_id=uuid4(),
        external_id=path.name,
        source_name=path.name,
        options=PdfParseOptions(column_detection=True),
    )
    understood = understand_document(
        parsed,
        file_hash=file_sha256(data),
        filename=path.name,
    )
    chunks = chunks_for_document(understood)
    payload = understood.metadata.get("understanding") or {}
    artifact = payload.get("artifact") or {}
    expected = _load_expected(path)
    scores = score_expected(understood, expected)
    result = {
        "file": str(path),
        "pages": understood.page_count,
        "sections": [section.heading for section in understood.sections],
        "tables": understood.table_count,
        "fields": [item.get("name") for item in payload.get("technical_fields") or []],
        "exact_literals": [item.get("value") for item in payload.get("exact_literals") or []],
        "quality": payload.get("quality"),
        "warnings": (payload.get("report") or {}).get("warnings") or [],
        "tree": payload.get("tree"),
        "canonical_markdown": (artifact.get("markdown_ref") if artifact.get("storage") == "artifact" else "inline"),
        "ast": (artifact.get("ast_ref") if artifact.get("storage") == "artifact" else "inline"),
        "semantic_unit_count": payload.get("semantic_unit_count"),
        "retrieval_hash": payload.get("retrieval_hash"),
        "canonical_hash": payload.get("canonical_hash"),
        "parsed_hash": payload.get("parsed_hash"),
        "file_hash": payload.get("file_hash"),
        "scores": scores,
        "ocr_vision": "NOT_IMPLEMENTED",
    }
    if find:
        result["find"] = find_literal(understood, chunks, find)
    if query:
        literal = find or _first_mask(payload)
        field_name = _field_in_query(payload, query)
        result["query"] = diagnose_question(
            understood,
            chunks,
            query,
            field_name=field_name,
            literal=literal,
            example=_example_token(query, payload),
        )
    if expected and scores:
        result["regression"] = regression_gate(expected.get("previous_scores") or scores, scores)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa Document Understanding sobre un PDF con text layer.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--find", default=None)
    parser.add_argument("--query", default=None)
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print(f"no está el archivo: {args.file}", file=sys.stderr)
        return 2
    report = evaluate(args.file, find=args.find, query=args.query)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    failed = report.get("regression") or []
    return 1 if failed else 0


def _load_expected(path: Path) -> dict | None:
    candidates = [
        path.with_suffix(".expected.json"),
        path.with_name("document.expected.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


def _first_mask(payload: dict) -> str | None:
    for item in payload.get("exact_literals") or []:
        if item.get("pattern_type") == "mask":
            return item.get("value")
    return None


def _field_in_query(payload: dict, query: str) -> str | None:
    for item in payload.get("technical_fields") or []:
        name = str(item.get("name") or "")
        if name and name in query:
            return name
    return None


def _example_token(query: str, payload: dict) -> str | None:
    known = {str(item.get("value")) for item in payload.get("exact_literals") or []}
    for token in query.split():
        if len(token) >= 6 and token.isalnum() and token not in known:
            return token
    return None


if __name__ == "__main__":
    raise SystemExit(main())
