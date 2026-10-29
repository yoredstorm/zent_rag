#!/usr/bin/env python
# =============================================================================
# P18.3-01 - CLI de validación del gold set
# =============================================================================
# Uso:
#   python -m src.scripts.validate_goldset_v1
#   python -m src.scripts.validate_goldset_v1 --strict-human
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys

from src.rag.evaluation.goldset_v1 import GOLDSET, METAMORPHIC, validate_goldset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida goldset P18.3")
    parser.add_argument("--goldset", default=str(GOLDSET))
    parser.add_argument("--metamorphic", default=str(METAMORPHIC))
    parser.add_argument("--strict-human", action="store_true")
    args = parser.parse_args(argv)
    from pathlib import Path

    result = validate_goldset(
        Path(args.goldset),
        Path(args.metamorphic),
        strict_human=args.strict_human,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))  # noqa: T201
    if result["status"] == "FAIL":
        return 1
    if result["status"] == "BLOCKED_HUMAN_REVIEW":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
